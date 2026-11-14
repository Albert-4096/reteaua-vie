"""O2: lines with no vehicle in our live recording („fără vehicul în datele live”).

Compares the SMTT GTFS timetable in force with our own recording of the City
Hall's live vehicles ($LIVE_DIR/vehicles/, one snapshot every ~15 s). Nothing is
fetched here. Method (ticket O-2):

1. Window [start, end): every scheduled trip whose span (first to last
   departure) overlaps it, and every snapshot in it.
2. Recording health first: a snapshot is healthy when realtimeAgeSec <= 120; a
   minute counts when it holds a healthy snapshot. Below 80 % healthy minutes the
   answer is `inregistrare_incompleta` and nothing is flagged.
3. Trip level: a trip is observed when its tripId is in a healthy snapshot of the
   window (a late vehicle keeps its trip id), or a vehicle of the same route and
   direction is in a healthy snapshot during its span (plus LATE_SLACK). A trip
   with no healthy snapshot in its span, or starting in the last LATE_SLACK of
   the window, is not judged either way.
4. Route level: `fara_vehicul` when the route had trips in service for at least
   one full scheduled headway (min 20 min) of healthy minutes and no healthy
   snapshot of the window shows a vehicle of the route; `partial` when the route
   was seen but some of its trips were not.

We infer from the City Hall's live data; we never say a trip was not run (only
SMTT classifies trips) and we never put a sum of money on it.
"""

from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.common import gtfs, vehicles
from app.common import provenance as prov
from app.common.timeutil import gtfs_service_start, iso, parse_iso
from app.config import TZ, real_now

log = logging.getLogger("reteaua_vie.live.missing")

HEALTHY_AGE_SEC = 120
MIN_HEALTHY_SHARE = 0.8
MIN_HEADWAY_SEC = 20 * 60
LATE_SLACK_SEC = 5 * 60
DEFAULT_WINDOW = timedelta(minutes=60)
MAX_WINDOW = timedelta(hours=24)
TOP_ROWS = 3

MODES = {"0": "tramvai", "900": "tramvai", "3": "autobuz", "700": "autobuz", "11": "troleibuz", "800": "troleibuz"}

# Prepared cases: a recorded window, so the demo works at any hour (never the 8 Nov demo clock).
CASES = {
    "case_l23": {
        "start": "2026-11-14T06:00:00+02:00",
        "end": "2026-11-14T10:41:00+02:00",
        "label": {"ro": "înregistrat 14 nov", "en": "recorded 14 Nov"},
    },
}

METHOD_NOTE = ("„Fără vehicul în datele live”: niciun vehicul al liniei în instantaneele bune (realtimeAgeSec ≤ 120 s) "
               "cât linia avea curse în orar, cel puțin un interval întreg dintre curse (min. 20 min). Deducem din "
               "datele live ale Primăriei, înregistrate de noi; nu e „cursă neefectuată” (încadrarea o face SMTT). / "
               "No vehicle of the line in any healthy snapshot while it had scheduled trips; inferred, not confirmed.")


# --- the recording, compacted per file ---------------------------------------------------

@dataclass(frozen=True)
class Snap:
    ts: float                               # unix seconds of fetchedAt
    healthy: bool
    routes: frozenset[str]
    trips: frozenset[str]
    route_dirs: frozenset[tuple[str, int]]


def _compact(snap: dict) -> Snap:
    age = snap.get("realtimeAgeSec")
    vs = snap.get("vehicles") or []
    return Snap(
        ts=parse_iso(snap["fetchedAt"]).timestamp(),
        healthy=isinstance(age, (int, float)) and age <= HEALTHY_AGE_SEC,
        routes=frozenset(v["routeId"] for v in vs if v.get("routeId")),
        trips=frozenset(v["tripId"] for v in vs if v.get("tripId")),
        route_dirs=frozenset((v["routeId"], v["directionId"]) for v in vs
                             if v.get("routeId") and v.get("directionId") in (0, 1)),
    )


@lru_cache(maxsize=64)
def _compact_file(path: str, size: int, mtime: float) -> tuple[Snap, ...]:
    return tuple(_compact(s) for s in vehicles._read_lines(Path(path)))


def recorded(start: datetime, end: datetime) -> tuple[list[Snap], list[str]]:
    """Snapshots with fetchedAt in [start, end), oldest first, and the files read."""
    s_ts, e_ts = start.timestamp(), end.timestamp()
    snaps: list[Snap] = []
    files: list[str] = []
    for path, hour in vehicles.recording_files():
        if hour.timestamp() + 3600 <= s_ts or hour.timestamp() >= e_ts:
            continue
        st = path.stat()
        files.append(path.name)
        snaps.extend(s for s in _compact_file(str(path), st.st_size, st.st_mtime) if s_ts <= s.ts < e_ts)
    snaps.sort(key=lambda s: s.ts)
    return snaps, files


# --- the timetable -----------------------------------------------------------------------

_TRIP_TABLES: dict[str, pd.DataFrame] = {}


def _trip_table(f: gtfs.Feed) -> pd.DataFrame:
    """One row per trip: route, direction, service, first and last departure (GTFS seconds)."""
    if f.sha256 not in _TRIP_TABLES:
        span = f.stop_times.groupby("trip_id").agg(first_sec=("dep_sec", "min"), last_sec=("dep_sec", "max"))
        t = f.trips[["trip_id", "route_id", "direction_id", "service_id"]].merge(
            span, left_on="trip_id", right_index=True)
        _TRIP_TABLES[f.sha256] = t
    return _TRIP_TABLES[f.sha256]


def scheduled_trips(f: gtfs.Feed, start: datetime, end: datetime) -> tuple[pd.DataFrame, dict[str, float]]:
    """Trips whose span overlaps [start, end), with absolute start_ts / end_ts, and the
    scheduled headway per route (median gap between trip starts per direction, that day)."""
    table = _trip_table(f)
    service = gtfs._service_dates(f.sha256)
    s_ts, e_ts = start.timestamp(), end.timestamp()
    parts, gaps = [], {}
    d: date = (start.astimezone(TZ) - timedelta(days=1)).date()  # trips past 24:00 of the day before
    while d <= end.astimezone(TZ).date():
        sids = service.get(d)
        if sids:
            sub = table[table.service_id.isin(sids)]
            base = gtfs_service_start(d).timestamp()
            sub = sub.assign(start_ts=base + sub.first_sec, end_ts=base + sub.last_sec, day=d)
            for (route, _dir), g in sub.groupby(["route_id", "direction_id"]):
                diffs = g.start_ts.sort_values().diff().dropna()
                gaps.setdefault(route, []).extend(diffs.tolist())
            parts.append(sub[(sub.start_ts < e_ts) & (sub.end_ts >= s_ts)])
        d += timedelta(days=1)
    trips = pd.concat(parts, ignore_index=True) if parts else table.iloc[0:0].assign(
        start_ts=[], end_ts=[], day=[])
    headway = {r: float(pd.Series(v).median()) for r, v in gaps.items() if v}
    return trips.sort_values("start_ts", kind="stable").reset_index(drop=True), headway


def trip_stop_time(f: gtfs.Feed, trip_id: str, day: date, not_before: float | None = None,
                   stop_id: str | None = None) -> dict | None:
    """The trip's stop and departure: at `stop_id`, else its first stop at or after `not_before`."""
    st = f.stop_times[f.stop_times.trip_id == trip_id].sort_values("stop_sequence")
    if st.empty:
        return None
    base = gtfs_service_start(day).timestamp()
    if stop_id is not None:
        st = st[st.stop_id == stop_id]
    elif not_before is not None:
        later = st[base + st.dep_sec >= not_before]
        st = later if not later.empty else st.tail(1)
    if st.empty:
        return None
    row = st.iloc[0]
    names = f.stops.set_index("stop_id")["stop_name"] if "stop_name" in f.stops else None
    sid = str(row.stop_id)
    return {
        "tripId": trip_id,
        "stopId": sid,
        "stopName": (str(names.get(sid)) if names is not None and sid in names.index else None),
        "scheduledTime": iso(datetime.fromtimestamp(base + int(row.dep_sec), tz=timezone.utc)),
    }


# --- the detector ------------------------------------------------------------------------

def _healthy_minutes(snaps: list[Snap], s_ts: float) -> set[int]:
    return {int((s.ts - s_ts) // 60) for s in snaps if s.healthy}


def classify_trips(trips: pd.DataFrame, snaps: list[Snap], s_ts: float, e_ts: float) -> list[str]:
    """Per trip: "observed", "missed" or "unknown".

    Observed: its tripId in any healthy snapshot of the window (a late vehicle keeps the
    trip's id: on 13 Nov the one bus of line 23 ran its trips up to an hour after the
    timetable), or a vehicle of the same route and direction during its span (+ slack).
    Unknown: no healthy snapshot in its span, or it starts in the last LATE_SLACK of the
    window (too soon to tell).
    """
    healthy = [s for s in snaps if s.healthy]
    times = [s.ts for s in healthy]
    trip_ids = frozenset().union(*(s.trips for s in healthy)) if healthy else frozenset()
    out = []
    for row in trips.itertuples(index=False):
        if row.trip_id in trip_ids:
            out.append("observed")
            continue
        lo = bisect.bisect_left(times, max(row.start_ts, s_ts))
        hi = bisect.bisect_left(times, min(row.end_ts + LATE_SLACK_SEC, e_ts))
        if lo >= hi or row.start_ts > e_ts - LATE_SLACK_SEC:
            out.append("unknown")
            continue
        key = (row.route_id, int(row.direction_id))
        seen = any(key in s.route_dirs for s in healthy[lo:hi])
        out.append("observed" if seen else "missed")
    return out


def _route_info(f: gtfs.Feed) -> dict[str, dict]:
    r = f.routes
    return {row.route_id: {"shortName": row.route_short_name or None, "longName": row.route_long_name or None,
                           "mode": MODES.get(str(row.route_type))}
            for row in r.itertuples(index=False)}


def detect(start: datetime, end: datetime, case: dict | None = None, repeat: bool = True) -> dict:
    """MissingLines for [start, end) (see app/models/live_missing.py); `repeat` fills repeatedDays."""
    start, end = start.astimezone(TZ), end.astimezone(TZ)
    s_ts, e_ts = start.timestamp(), end.timestamp()
    snaps, files = recorded(start, end)
    minutes = max(1, int(-(-(e_ts - s_ts) // 60)))
    healthy_min = _healthy_minutes(snaps, s_ts)
    share = round(len(healthy_min) / minutes, 4)
    status = "ok" if share >= MIN_HEALTHY_SHARE else "inregistrare_incompleta"

    f = gtfs.feed(start)
    trips, headway = scheduled_trips(f, start, end)
    routes_out: list[dict] = []
    by_mode: list[dict] = []
    if status == "ok" and not trips.empty:
        trips = trips.assign(result=classify_trips(trips, snaps, s_ts, e_ts))
        info = _route_info(f)
        last_seen: dict[str, float] = {}
        for s in snaps:
            if s.healthy:
                for r in s.routes:
                    last_seen[r] = s.ts
        for route, g in trips.groupby("route_id", sort=False):
            service_min: set[int] = set()
            for row in g.itertuples(index=False):
                a = int((max(row.start_ts, s_ts) - s_ts) // 60)
                b = int(-(-(min(row.end_ts, e_ts) - s_ts) // 60))
                service_min.update(range(a, b))
            need = max(MIN_HEADWAY_SEC, headway.get(route, 0.0)) / 60
            missed = g[g.result == "missed"]
            if route not in last_seen and len(service_min & healthy_min) >= need:
                state, since_ts = "fara_vehicul", max(s_ts, float(g.start_ts.min()))
            elif route in last_seen and not missed.empty:
                state, since_ts = "partial", max(s_ts, float(missed.start_ts.min()))
            else:
                continue
            first = None
            if not missed.empty:
                m = missed.iloc[0]
                first = trip_stop_time(f, m.trip_id, m.day, not_before=max(s_ts, float(m.start_ts)))
            meta = info.get(route, {})
            routes_out.append({
                "routeId": route,
                "shortName": meta.get("shortName"),
                "longName": meta.get("longName"),
                "mode": meta.get("mode"),
                "state": state,
                "tripsInService": int(len(g)),
                "tripsObserved": int((g.result == "observed").sum()),
                "since": iso(datetime.fromtimestamp(since_ts, tz=timezone.utc)),
                "lastSeenAt": (iso(datetime.fromtimestamp(last_seen[route], tz=timezone.utc))
                               if route in last_seen else None),
                "firstMissedTrip": first,
                "repeatedDays": None,
            })
        if repeat:
            other_days = _flags_other_days(start, end)
            for r in routes_out:
                r["repeatedDays"] = 1 + sum(1 for flags in other_days if (r["routeId"], r["state"]) in flags)
        routes_out.sort(key=lambda r: (r["state"] != "fara_vehicul", -(r["tripsInService"] - r["tripsObserved"]),
                                       r["shortName"] or r["routeId"]))
        modes = trips.assign(mode=trips.route_id.map(lambda r: info.get(r, {}).get("mode")))
        for mode in ("autobuz", "troleibuz", "tramvai"):
            g = modes[modes["mode"] == mode]
            n, k = int(len(g)), int((g.result == "missed").sum())
            by_mode.append({"mode": mode, "tripsScheduled": n, "tripsWithNoVehicle": k,
                            "share": round(k / n, 4) if n else None})

    n_healthy = sum(1 for s in snaps if s.healthy)
    rec_time = datetime.fromtimestamp(snaps[-1].ts, tz=timezone.utc) if snaps else real_now()
    provenance = [
        f.provenance.model_dump(),
        prov.vehicles_provenance(rec_time, (
            f"Fereastra / window {iso(start)} – {iso(end)}; {len(snaps)} instantanee / snapshots, {n_healthy} bune "
            f"(realtimeAgeSec ≤ {HEALTHY_AGE_SEC} s); {share:.0%} din minute acoperite / of minutes covered; "
            f"fișiere / files: {', '.join(files) or 'niciunul / none'}")).model_dump(),
        prov.provenance("Rețeaua Vie O2, detectorul de linii fără vehicul / no-vehicle detector", real_now(),
                        None, None, METHOD_NOTE).model_dump(),
    ]
    if status != "ok":
        provenance.append(prov.provenance(
            "Rețeaua Vie O2", real_now(), None, None,
            f"Înregistrare incompletă: {share:.0%} din minute au date bune (< {MIN_HEALTHY_SHARE:.0%}); "
            f"nu marcăm nimic / recording incomplete, nothing flagged").model_dump())
    return {
        "window": {"start": iso(start), "end": iso(end)},
        "status": status,
        "case": case,
        "recording": {"snapshots": len(snaps), "healthySnapshots": n_healthy, "healthyShare": share,
                      "files": files},
        "routes": routes_out,
        "byMode": by_mode,
        "provenance": provenance,
    }


REPEAT_DAYS = 7  # look this many days back and forward for the same window


@lru_cache(maxsize=128)
def _past_flags(s_ts: float, e_ts: float) -> frozenset[tuple[str, str]]:
    """(route, state) flagged in a past window; empty when the recording there is incomplete."""
    r = detect(datetime.fromtimestamp(s_ts, tz=timezone.utc), datetime.fromtimestamp(e_ts, tz=timezone.utc),
               repeat=False)
    return frozenset((x["routeId"], x["state"]) for x in r["routes"]) if r["status"] == "ok" else frozenset()


def _flags_other_days(start: datetime, end: datetime) -> list[frozenset]:
    """The flags of the same clock-time window on every other recorded day (R4 „repetat {n} zile”)."""
    files = vehicles.recording_files()
    if not files:
        return []
    first, last = files[0][1].timestamp(), files[-1][1].timestamp() + 3600
    now_ts = real_now().timestamp()
    out = []
    for k in range(-REPEAT_DAYS, REPEAT_DAYS + 1):
        if k == 0:
            continue
        s, e = start + timedelta(days=k), end + timedelta(days=k)  # wall-clock shift (Bucharest)
        s_ts, e_ts = s.timestamp(), e.timestamp()
        if e_ts <= first or s_ts >= last or e_ts > now_ts:
            continue
        out.append(_past_flags(s_ts, e_ts))
    return out


def with_decisions(result: dict) -> dict:
    """A copy of a MissingLines result whose rows carry the decision in force (R4)."""
    from app.live import triage

    decided = triage.latest()
    win = result["window"]
    rows = [{**r, "decision": decided.get((r["routeId"], win["start"], win["end"]))} for r in result["routes"]]
    try:   # C2 (v2.29): additive `serviceConfirmation`; a failure there never breaks O2
        from app.checkin import confirm
        rows = confirm.annotate(rows, win)
    except Exception:
        log.exception("C2 service confirmation failed; rows without it")
    return {**result, "routes": rows}


def confirmed_gap(route_id: str, at: datetime) -> dict | None:
    """S1 hook (app/cityapp/status.py): {"since", "note"} when a person confirmed no vehicle, else None."""
    from app.live import triage

    return triage.confirmed_gap(route_id, at)


def live_window(minutes: timedelta = DEFAULT_WINDOW) -> tuple[datetime, datetime]:
    """The last `minutes` of the real clock (never the demo clock: no recording exists on 8 Nov)."""
    end = real_now().replace(microsecond=0)
    return end - minutes, end


@lru_cache(maxsize=4)
def prepared(case_id: str) -> dict:
    """A prepared case (recorded window, closed files): computed once per process."""
    c = CASES[case_id]
    return detect(parse_iso(c["start"]), parse_iso(c["end"]), case={"id": case_id, "label": c["label"]})


def brief(result: dict) -> dict:
    """The step 0 slice: counts and the top rows."""
    routes = result["routes"]
    return {
        "window": result["window"],
        "status": result["status"],
        "case": result["case"],
        "count": sum(1 for r in routes if r["state"] == "fara_vehicul"),
        "partialCount": sum(1 for r in routes if r["state"] == "partial"),
        "rows": routes[:TOP_ROWS],
    }
