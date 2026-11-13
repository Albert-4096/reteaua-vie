"""Patched GTFS: the planned timetable minus the stops a closure suspends (SPEC §6.2).

A router must see a suspended stop as not served, so we remove its scheduled
stop_times inside the closure window from a copy of the GTFS (never GTFS-RT:
routers treat alerts as text only).

Base feed: the timetable in force before the works (impact.timetable_for on the
window start; 4.29 for Mocioni, else the current feed).

Which rows: the closure's (stop, route, direction) rows that count as lost
after the clerk's decisions (impact.counts_as_lost), exactly what the Impact
counts.

How, per trip: a trip of a lost (route, direction) that calls at a lost stop
inside the window on some service date is split by date. The original trip
keeps every other date (new service id); one copy per distinct set of removed
calls runs only on the affected dates, without those calls. A copy with fewer
than two calls left is dropped (the whole trip is cancelled). Nothing changes
outside the window.

The result is a valid GTFS zip (empty tables dropped: R5 rejects the empty
frequencies.txt), cached in $DATA_DIR/cache/r5/gtfs/ by a hash of the base
feed, the window and the lost rows. Same decisions, same file.

Public:
    base_feed(window_start) -> (path, version)
    clean_base(path) -> Path                  the base feed, R5-loadable
    lost_rows(closure_id) -> (closure, set of (stop, route, dir))
    patched_for(closure, lost, frequencies=None) -> PatchedFeed   (scenarios: never stored)
    patched_feed(closure_id) -> PatchedFeed
    patched_combined([(closure, lost), ...], at) -> PatchedFeed   (M2: every closure active at `at`)
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from app.common import gtfs, state
from app.common.errors import not_found
from app.common.timeutil import gtfs_service_start, parse_iso
from app.config import TZ, get_settings
from app.m1_disruption import impact as imp

PATCH_VERSION = 1
FREQ_VERSION = 2    # only in keys with frequencies, so plain patches (and their R5 networks) stay cached
Key = tuple[str, str, int]

_lock = threading.Lock()


# --- base feed ------------------------------------------------------------------------


def base_feed(window_start: datetime | str | None) -> tuple[Path, str | None]:
    """The GTFS zip in force before the works start, and its version."""
    tt = imp.timetable_for(window_start)
    if isinstance(tt, imp.HistoryTimetable):
        return tt.path, tt.version
    f = gtfs.feed()
    return f.path, f.version


def _cache_dir() -> Path:
    d = get_settings().cache_dir / "r5" / "gtfs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_tables(path: Path) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.endswith(".txt"):
                continue
            raw = z.read(name).decode("utf-8-sig")
            out[name[:-4]] = pd.read_csv(io.StringIO(raw), dtype=str, keep_default_na=False)
    return out


def _write_zip(tables: dict[str, pd.DataFrame], dest: Path) -> None:
    tmp = dest.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, df in tables.items():
            if df is None or df.empty:
                continue  # R5: "Table is present in zip file, but it has no entries"
            z.writestr(f"{name}.txt", df.to_csv(index=False))
    tmp.replace(dest)


def clean_base(path: Path) -> Path:
    """The base feed without empty tables, cached by its hash (R5 cannot load the raw SMTT zip)."""
    dest = _cache_dir() / f"base_v{PATCH_VERSION}_{_file_sha(path)[:16]}.zip"
    with _lock:
        if not dest.is_file():
            _write_zip(_read_tables(path), dest)
    return dest


# --- which rows ---------------------------------------------------------------------------


def lost_rows(closure_id: str) -> tuple[dict, set[Key]]:
    """The stored closure and its lost (stop, route, direction) rows after decisions."""
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id}.")
    analysis = state.read("closures", closure_id, state.PART_ANALYSIS)
    if analysis is None:
        raise not_found(f"Closure {closure_id} was never analyzed.", code="NOT_ANALYZED")
    return closure, {imp.row_key(r) for r in analysis["stops"] if imp.counts_as_lost(r)}


# --- service dates of a feed ----------------------------------------------------------------

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _ymd(v: str) -> date:
    return datetime.strptime(v, "%Y%m%d").date()


def service_dates(calendar: pd.DataFrame, calendar_dates: pd.DataFrame) -> dict[str, set[date]]:
    """{service_id: dates it runs}, from calendar.txt + calendar_dates.txt."""
    out: dict[str, set[date]] = {}
    for row in calendar.itertuples(index=False):
        d, end = _ymd(row.start_date), _ymd(row.end_date)
        days = out.setdefault(row.service_id, set())
        while d <= end:
            if getattr(row, _WEEKDAYS[d.weekday()]) == "1":
                days.add(d)
            d += timedelta(days=1)
    for row in calendar_dates.itertuples(index=False):
        days = out.setdefault(row.service_id, set())
        if row.exception_type == "1":
            days.add(_ymd(row.date))
        elif row.exception_type == "2":
            days.discard(_ymd(row.date))
    return out


def _hms(col: pd.Series) -> np.ndarray:
    parts = col.str.split(":", expand=True).astype(int)
    return (parts[0] * 3600 + parts[1] * 60 + parts[2]).to_numpy(dtype=np.int64)


# --- the patch ------------------------------------------------------------------------------


@dataclass(frozen=True)
class PatchedFeed:
    closure_id: str
    path: Path                  # the patched zip (R5-loadable)
    base_path: Path             # the clean base zip (R5-loadable)
    base_source: Path           # the original SMTT zip the base was made from
    base_version: str | None
    lost: frozenset[Key]
    trips_split: int            # trips with at least one call removed on some date
    trips_cancelled: int        # trip copies dropped (fewer than two calls left)
    calls_removed: int          # stop_times removed, summed over the dates they were removed on
    trips_added: int = 0        # frequency mitigation
    frequency_notes: tuple[str, ...] = ()


def patch_tables(t: dict[str, pd.DataFrame], lost: set[Key], start: datetime, end: datetime,
                 prefix: str = "rv") -> tuple[dict, dict]:
    """Apply the closure to GTFS tables (all str columns). Returns (new tables, stats)."""
    trips, st = t["trips"].copy(), t["stop_times"]
    cal = t.get("calendar", pd.DataFrame())
    cd = t.get("calendar_dates", pd.DataFrame(columns=["service_id", "date", "exception_type"]))
    stats = {"trips_split": 0, "trips_cancelled": 0, "calls_removed": 0}
    if not lost:
        return t, stats
    trips["_dir"] = trips["direction_id"].replace("", "0").astype(int)
    lost_routes = {(r, d) for _, r, d in lost}
    cand_trips = trips[[(r, d) in lost_routes for r, d in zip(trips["route_id"], trips["_dir"])]]
    trip_info = cand_trips.set_index("trip_id")[["route_id", "_dir", "service_id"]]
    sub = st[st["trip_id"].isin(trip_info.index)].copy()
    sub["route_id"] = trip_info.loc[sub["trip_id"], "route_id"].to_numpy()
    sub["_dir"] = trip_info.loc[sub["trip_id"], "_dir"].to_numpy()
    is_lost = np.array([(s, r, d) in lost for s, r, d in zip(sub["stop_id"], sub["route_id"], sub["_dir"])],
                       dtype=bool)
    sub = sub[is_lost]
    if sub.empty:
        return t, stats
    sub["_sec"] = _hms(sub["departure_time"].where(sub["departure_time"] != "", sub["arrival_time"]))
    days_of = service_dates(cal, cd)
    # service dates that can touch the window (trips past 24:00 start the day before)
    d0 = start.astimezone(TZ).date() - timedelta(days=1)
    d1 = (end - timedelta(seconds=1)).astimezone(TZ).date()
    t0, t1 = int(start.timestamp()), int(end.timestamp())

    # per trip: {service date: frozenset(stop_sequence removed)}
    removed: dict[str, dict[date, frozenset[str]]] = {}
    for trip_id, g in sub.groupby("trip_id", sort=False):
        sid = trip_info.at[trip_id, "service_id"]
        for d in sorted(x for x in days_of.get(sid, ()) if d0 <= x <= d1):
            base = int(gtfs_service_start(d).timestamp())
            ts = base + g["_sec"].to_numpy()
            hit = g["stop_sequence"].to_numpy()[(ts >= t0) & (ts < t1)]
            if len(hit):
                removed.setdefault(trip_id, {})[d] = frozenset(hit.tolist())
    if not removed:
        return t, stats

    st_by_trip = {tid: g for tid, g in st[st["trip_id"].isin(list(removed))].groupby("trip_id", sort=False)}
    new_trips, new_st, new_cd = [], [], []
    keep_trip = trips.drop(columns="_dir")
    trip_rows = keep_trip.set_index("trip_id")
    service_alias: dict[tuple[str, frozenset[date]], str] = {}

    def service_for(dates: frozenset[date], tag: str) -> str:
        key = (tag, dates)
        if key not in service_alias:
            sid = f"{prefix}_{tag}_{hashlib.sha1(','.join(sorted(d.isoformat() for d in dates)).encode()).hexdigest()[:10]}"
            service_alias[key] = sid
            new_cd.extend({"service_id": sid, "date": d.strftime("%Y%m%d"), "exception_type": "1"}
                          for d in sorted(dates))
        return service_alias[key]

    replace_service: dict[str, str] = {}
    for trip_id, by_date in removed.items():
        stats["trips_split"] += 1
        sid = trip_info.at[trip_id, "service_id"]
        rest = frozenset(days_of.get(sid, set()) - set(by_date))
        replace_service[trip_id] = service_for(rest, f"keep_{sid}") if rest else ""
        groups: dict[frozenset[str], set[date]] = {}
        for d, seqs in by_date.items():
            groups.setdefault(seqs, set()).add(d)
        for n, (seqs, dates) in enumerate(sorted(groups.items(), key=lambda kv: min(kv[1]))):
            calls = st_by_trip[trip_id]
            kept = calls[~calls["stop_sequence"].isin(seqs)]
            stats["calls_removed"] += (len(calls) - len(kept)) * len(dates)
            if len(kept) < 2:
                stats["trips_cancelled"] += 1
                continue
            copy_id = f"{trip_id}_{prefix}{n}"
            row = trip_rows.loc[trip_id].to_dict()
            row.update(trip_id=copy_id, service_id=service_for(frozenset(dates), "only"))
            new_trips.append(row)
            new_st.append(kept.assign(trip_id=copy_id))

    out = dict(t)
    tr = keep_trip.copy()
    svc = tr["trip_id"].map(replace_service)
    tr.loc[svc.notna(), "service_id"] = svc[svc.notna()]
    gone = tr["service_id"] == ""                      # every date was patched: only the copies run
    st_out = st[~st["trip_id"].isin(set(tr.loc[gone, "trip_id"]))]
    tr = tr[~gone]
    if new_trips:
        tr = pd.concat([tr, pd.DataFrame(new_trips)], ignore_index=True)
        st_out = pd.concat([st_out] + new_st, ignore_index=True)
    out["trips"] = tr
    out["stop_times"] = st_out[[c for c in t["stop_times"].columns]]
    if new_cd:
        out["calendar_dates"] = pd.concat([cd, pd.DataFrame(new_cd)], ignore_index=True)
    return out, stats


def _patch_key(base_name: str, window: dict, lost: set[Key], frequencies: list[dict] | None) -> str:
    extra = [FREQ_VERSION, frequencies] if frequencies else []
    payload = json.dumps([PATCH_VERSION, base_name, window, sorted(lost), *extra], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


_memo: dict[str, PatchedFeed] = {}


def patched_for(closure: dict, lost: set[Key], frequencies: list[dict] | None = None) -> PatchedFeed:
    """The GTFS without `lost` calls inside the closure window (cached by window + rows + frequencies).

    `closure` needs `window` (and `id`, used only in the file name). Works for scenarios that
    are never stored. `frequencies` = [{"routeId", "headwayMinutes"}] (SPEC §6.4 mitigation).
    """
    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    src, version = base_feed(start)
    base = clean_base(src)
    key = _patch_key(base.name, closure["window"], lost, frequencies)
    if key in _memo and _memo[key].path.is_file():
        return _memo[key]
    tag = "".join(ch for ch in str(closure.get("id") or "adhoc") if ch.isalnum() or ch in "_-")[:60]
    dest = _cache_dir() / f"patched_{tag}_{key}.zip"
    meta = dest.with_suffix(".json")
    with _lock:
        if dest.is_file() and meta.is_file():
            stats = json.loads(meta.read_text())
        else:
            tables, stats = patch_tables(_read_tables(base), lost, start, end)
            if frequencies:
                tables, fstats = add_frequency_trips(tables, frequencies, start, end, lost)
                stats.update(fstats)
            _write_zip(tables, dest)
            meta.write_text(json.dumps(stats))
    pf = PatchedFeed(closure_id=str(closure.get("id") or ""), path=dest, base_path=base, base_source=src,
                     base_version=version, lost=frozenset(lost), trips_split=stats["trips_split"],
                     trips_cancelled=stats["trips_cancelled"], calls_removed=stats["calls_removed"],
                     trips_added=stats.get("trips_added", 0), frequency_notes=tuple(stats.get("frequency_notes", ())))
    _memo[key] = pf
    return pf


def patched_feed(closure_id: str) -> PatchedFeed:
    """The patched GTFS of a stored closure with its current decisions."""
    closure, lost = lost_rows(closure_id)
    return patched_for(closure, lost)


def patched_combined(items: list[tuple[dict, set[Key]]], at: datetime) -> PatchedFeed:
    """One GTFS without the lost calls of several closures (each inside its own window).

    For routing at time `at` (M2): the base is the timetable in force at `at`; closures are
    applied one after another, in a stable order.
    """
    src, version = base_feed(at)
    base = clean_base(src)
    items = sorted(items, key=lambda it: (str(it[0].get("id")), it[0]["window"]["start"]))
    payload = json.dumps([PATCH_VERSION, base.name, [[c.get("id"), c["window"], sorted(lost)] for c, lost in items]],
                         sort_keys=True)
    key = hashlib.sha256(payload.encode()).hexdigest()[:16]
    if key in _memo and _memo[key].path.is_file():
        return _memo[key]
    dest = _cache_dir() / f"patched_multi_{key}.zip"
    meta = dest.with_suffix(".json")
    with _lock:
        if dest.is_file() and meta.is_file():
            stats = json.loads(meta.read_text())
        else:
            tables = _read_tables(base)
            stats = {"trips_split": 0, "trips_cancelled": 0, "calls_removed": 0}
            for n, (c, lost) in enumerate(items):
                tables, st = patch_tables(tables, lost, parse_iso(c["window"]["start"]),
                                          parse_iso(c["window"]["end"]), prefix=f"rv{n}")
                for k in stats:
                    stats[k] += st[k]
            _write_zip(tables, dest)
            meta.write_text(json.dumps(stats))
    lost_all = frozenset(k for _, lost in items for k in lost)
    pf = PatchedFeed(closure_id=",".join(str(c.get("id")) for c, _ in items), path=dest, base_path=base,
                     base_source=src, base_version=version, lost=lost_all, trips_split=stats["trips_split"],
                     trips_cancelled=stats["trips_cancelled"], calls_removed=stats["calls_removed"])
    _memo[key] = pf
    return pf


def _hms_str(sec: int) -> str:
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def add_frequency_trips(t: dict[str, pd.DataFrame], frequencies: list[dict], start: datetime,
                        end: datetime, lost: set[Key] = frozenset()) -> tuple[dict, dict]:
    """SPEC §6.4 mitigation `frequency`: a line runs at least every N minutes inside the window.

    Per service date and direction, every gap longer than N minutes between two scheduled
    departures (first stop) inside the window gets extra trips every N minutes. An extra trip
    copies the trip before the gap, shifted in time, so it keeps the (patched) pattern of a
    shortened line. Service hours are not extended. Each extra trip runs only on its date, and
    never calls at a `lost` (stop, route, direction) inside the window.
    """
    trips, st = t["trips"], t["stop_times"]
    cal = t.get("calendar", pd.DataFrame())
    cd = t.get("calendar_dates", pd.DataFrame(columns=["service_id", "date", "exception_type"]))
    days_of = service_dates(cal, cd)
    t0, t1 = int(start.timestamp()), int(end.timestamp())
    d0 = start.astimezone(TZ).date() - timedelta(days=1)
    d1 = (end - timedelta(seconds=1)).astimezone(TZ).date()
    new_trips, new_st, new_cd, notes = [], [], [], []
    added_total = 0
    for f in frequencies:
        route, headway = str(f.get("routeId")), int(f.get("headwayMinutes") or 0)
        if headway <= 0:
            notes.append(f"{route}: interval invalid / invalid headway")
            continue
        h = headway * 60
        rt = trips[trips["route_id"] == route]
        if rt.empty:
            notes.append(f"{route}: linia nu e în orar / route not in the timetable")
            continue
        calls = st[st["trip_id"].isin(rt["trip_id"])]
        first = calls.assign(_seq=calls["stop_sequence"].astype(int)).sort_values("_seq").groupby("trip_id").first()
        first_sec = pd.Series(_hms(first["departure_time"]), index=first.index)
        added = 0
        d = d0
        while d <= d1:
            base = int(gtfs_service_start(d).timestamp())
            active = {sid for sid, days in days_of.items() if d in days}
            for _, g in rt[rt["service_id"].isin(active)].groupby(rt["direction_id"].replace("", "0")):
                deps = sorted((base + int(first_sec[tid]), tid) for tid in g["trip_id"] if tid in first_sec.index)
                deps = [x for x in deps if t0 <= x[0] < t1]
                for (a, tid), (b, _) in zip(deps, deps[1:]):
                    k = 1
                    while a + k * h < b - 60:          # keep at least one minute before the next trip
                        shift = k * h
                        new_id = f"{tid}_f{d:%Y%m%d}_{k}"
                        sid = f"rvf_{d:%Y%m%d}"
                        row = trips[trips["trip_id"] == tid].iloc[0].to_dict()
                        row.update(trip_id=new_id, service_id=sid)
                        new_trips.append(row)
                        tpl = st[st["trip_id"] == tid].copy()
                        for col in ("arrival_time", "departure_time"):
                            ok = tpl[col] != ""
                            tpl.loc[ok, col] = [_hms_str(x + shift) for x in _hms(tpl.loc[ok, col])]
                        ts = base + _hms(tpl["departure_time"])
                        dir_ = int(row["direction_id"] or 0)
                        drop = [(sid_, route, dir_) in lost and t0 <= x < t1 for sid_, x in zip(tpl["stop_id"], ts)]
                        tpl = tpl[[not x for x in drop]]
                        if len(tpl) < 2:
                            new_trips.pop()
                            k += 1
                            continue
                        new_st.append(tpl.assign(trip_id=new_id))
                        new_cd.append({"service_id": sid, "date": d.strftime("%Y%m%d"), "exception_type": "1"})
                        added += 1
                        k += 1
            d += timedelta(days=1)
        added_total += added
        notes.append(f"{route}: {added} curse adăugate, cel mult {headway} min între plecări în fereastră"
                     if added else f"{route}: nicio cursă de adăugat (nu circulă în fereastră sau are deja "
                                   f"cel mult {headway} min)")
    out = dict(t)
    if new_trips:
        out["trips"] = pd.concat([trips, pd.DataFrame(new_trips)], ignore_index=True)
        out["stop_times"] = pd.concat([st] + new_st, ignore_index=True)
        cd_new = pd.DataFrame(new_cd).drop_duplicates()
        out["calendar_dates"] = pd.concat([cd, cd_new], ignore_index=True)
    return out, {"trips_added": added_total, "frequency_notes": notes}
