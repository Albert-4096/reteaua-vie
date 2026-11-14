"""Build L0, hour file by hour file:  uv run python -m app.observed.build [--max-hours N]

Stage A, per recording file: the reports, de-duplicated on (vehicle, updatedAt) (a vehicle
whose report did not change between two 15 s polls counts once). Time of a report = its
`updatedAt` (the vehicle's own clock), not the poll time.

Stage B, per hour H: the reports of H-1, H and H+1, grouped per (trip, vehicle). Each group is
matched to the GTFS trip of its service date (the date, among the report's local day and the
day before, whose planned time is closest: a trip after midnight keeps the previous day's
service date, as GTFS times past 24:00 do). Then, per stop of the trip, in stop order:

- observed (`STOPPED_AT` seen): arrival = midpoint between the last report before the stop
  and the first `STOPPED_AT` report; departure = midpoint between the last `STOPPED_AT` report
  and the next one; dwell = departure - arrival. Error = half of each bracket.
  No arrival at the first stop (the vehicle waits there between trips), no departure at the last.
- interpolated (the vehicle passed the stop between two reports without a `STOPPED_AT`):
  one passing time, linear in metres along the GTFS shape between the two reports' positions.
- no event when the two reports around the stop are more than MAX_GAP_SEC apart (the 292 s gap
  at the start of the recording, a GPS silence) or when the trip was not recorded there.

Reports that go back along the trip (an earlier stop after a later one) are dropped.
Our stop delay = arrival (else departure, for the first stop) - planned time; `feed_delay_sec`
= the delaySec of the report the event comes from, kept for comparison.

Events are stored in the hour of their arrival (else departure), segments in the hour of the
departure from their first stop. Hour H is built once its file is closed and the recording has
gone READY_AFTER_SEC past its end (the next hour's reports close its last brackets); a built
hour is never rebuilt.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.common import vehicles
from app.common.geo import project_lonlats
from app.common.timeutil import from_unix, iso
from app.config import TZ, ensure_dirs, get_settings
from app.observed import timetable as tt

log = logging.getLogger("reteaua_vie.observed")

VERSION = 1
MAX_GAP_SEC = 180        # longest report bracket we time a stop from
READY_AFTER_SEC = 600    # recording needed past an hour's end before that hour is built
MAX_RUN_SEC = 3600       # a stop-to-stop run longer than this is a data error, not a run
GAP_NOTE_SEC = 60        # a pause between two snapshots longer than this is listed in the summary
DAY_TYPES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def out_dir() -> Path:
    return get_settings().cache_dir / "observed" / f"v{VERSION}"


def stem(hour: datetime) -> str:
    return hour.astimezone(timezone.utc).strftime("%Y%m%d-%H")


# --- parquet helpers ----------------------------------------------------------------------------

def _write(df: pd.DataFrame, path: Path, meta: dict | None = None) -> None:
    table = pa.Table.from_pandas(df, preserve_index=False)
    if meta is not None:
        table = table.replace_schema_metadata({**(table.schema.metadata or {}),
                                               b"observed": json.dumps(meta).encode()})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(table, tmp)
    tmp.replace(path)


def _meta(path: Path) -> dict:
    raw = (pq.read_schema(path).metadata or {}).get(b"observed")
    return json.loads(raw) if raw else {}


# --- stage A: reports of one recording file ---------------------------------------------------------

REPORT_COLUMNS = ["t", "vid", "trip", "route", "dir", "stop", "seq", "stopped", "delay",
                  "lon", "lat", "x", "y", "speed"]


def parse_file(path: Path) -> tuple[pd.DataFrame, dict]:
    """(reports, {snapshots, first, last}) of one recording file; tolerates a cut last line."""
    rows: list[tuple] = []
    seen: set[tuple[str, int]] = set()
    snaps = vehicles._read_lines(path)
    for snap in snaps:
        fetched = int(vehicles.snapshot_time(snap).timestamp())
        for v in snap.get("vehicles") or []:
            if v.get("lat") is None or v.get("lon") is None or not v.get("tripId"):
                continue
            upd = v.get("updatedAt")
            t = int(upd) if isinstance(upd, (int, float)) else fetched
            key = (str(v.get("id")), t)
            if key in seen:
                continue
            seen.add(key)
            seq = v.get("stopSequence")
            d = v.get("delaySec")
            rows.append((t, key[0], str(v["tripId"]), str(v.get("routeId") or ""),
                         int(v["directionId"]) if v.get("directionId") in (0, 1) else -1,
                         str(v["stopId"]) if v.get("stopId") is not None else "",
                         int(seq) if isinstance(seq, (int, float)) else -1,
                         v.get("status") == "STOPPED_AT",
                         float(d) if isinstance(d, (int, float)) else np.nan,
                         float(v["lon"]), float(v["lat"]),
                         float(v["speed"]) if isinstance(v.get("speed"), (int, float)) else np.nan))
    df = pd.DataFrame(rows, columns=[c for c in REPORT_COLUMNS if c not in ("x", "y")])
    xy = project_lonlats(zip(df["lon"], df["lat"])) if len(df) else np.zeros((0, 2))
    df["x"], df["y"] = xy[:, 0], xy[:, 1]
    df = df[REPORT_COLUMNS].astype({"t": "int64", "dir": "int8", "seq": "int16", "speed": "float32",
                                    "delay": "float32"})
    times = sorted(vehicles.snapshot_time(s) for s in snaps)
    gaps = [[iso(a), int((b - a).total_seconds())] for a, b in zip(times, times[1:])
            if (b - a).total_seconds() > GAP_NOTE_SEC]
    stats = {"snapshots": len(snaps), "first": iso(times[0]) if times else None,
             "last": iso(times[-1]) if times else None, "gaps": gaps}
    return df, stats


def hour_reports(path: Path, closed: bool) -> tuple[pd.DataFrame, dict]:
    """Stage A for one file, cached as Parquet once the file is closed."""
    cache = out_dir() / "reports" / f"{path.name[:-len('.jsonl.gz')]}.parquet"
    if closed and cache.is_file():
        try:
            return pd.read_parquet(cache), _meta(cache)
        except Exception:
            pass
    df, stats = parse_file(path)
    if closed:
        _write(df, cache, stats)
    return df, stats


# --- stage B: stop events and segments --------------------------------------------------------------

_DAY_SHA: dict[date, tt.Timetable] = {}


def _timetable(day: date) -> tt.Timetable:
    if day not in _DAY_SHA:
        _DAY_SHA[day] = tt.timetable_on(day)
    return _DAY_SHA[day]


def match_trip(trip_id: str, t0: float, seq0: int) -> tuple[tt.TripPlan, date, float] | None:
    """(plan, service date, unix time zero of that date) for a report of a trip, or None."""
    d0 = from_unix(t0).date()
    best = None
    for d in (d0, d0 - timedelta(days=1)):
        plan = _timetable(d).trips.get(trip_id)
        if plan is None:
            continue
        j = int(np.clip(np.searchsorted(plan.seq, seq0), 0, len(plan.seq) - 1))
        base = tt.service_base(d)
        cost = abs(t0 - (base + float(plan.dep_sec[j])))
        if not tt.runs_on(plan, d):
            cost += 12 * 3600
        if best is None or cost < best[0]:
            best = (cost, plan, d, base)
    return None if best is None else best[1:]


EVENT_COLUMNS = ["service_date", "trip_id", "route_id", "direction_id", "vehicle_id", "stop_id",
                 "stop_sequence", "stop_index", "n_stops", "sched_arr", "sched_dep", "arr", "dep",
                 "arr_err", "dep_err", "dwell_sec", "delay_sec", "feed_delay_sec", "interpolated",
                 "event_ts", "trip_sched_start", "trip_sched_end", "shape_id", "feed_version"]
SEGMENT_COLUMNS = ["service_date", "trip_id", "route_id", "direction_id", "shape_id", "from_stop_id",
                   "to_stop_id", "from_sequence", "to_sequence", "from_index", "dep_ts", "arr_ts",
                   "run_sec", "sched_run_sec", "dist_m", "hour_local", "day_type", "from_interpolated",
                   "to_interpolated", "feed_version"]


def trip_events(g: pd.DataFrame, plan: tt.TripPlan, day: date, base: float) -> tuple[list, list]:
    """Stop events and segments of one recorded trip run (reports of one trip and vehicle)."""
    g = g.sort_values("t")
    idx = np.searchsorted(plan.seq, g["seq"].to_numpy())
    ok = (idx < len(plan.seq)) & (plan.seq[np.minimum(idx, len(plan.seq) - 1)] == g["seq"].to_numpy())
    g, idx = g[ok], idx[ok]
    if len(g) == 0:
        return [], []
    stopped = g["stopped"].to_numpy(bool)
    p = 2 * idx - (~stopped).astype(int)          # IN_TRANSIT_TO k = 2k-1, STOPPED_AT k = 2k
    keep = p >= np.maximum.accumulate(p)          # drop reports that go back along the trip
    g, idx, stopped, p = g[keep], idx[keep], stopped[keep], p[keep]
    t = g["t"].to_numpy(float)
    x, y = g["x"].to_numpy(float), g["y"].to_numpy(float)
    delay = g["delay"].to_numpy(float)
    geom = tt.pattern_geometry(plan)
    n = len(plan.seq)
    vid = str(g["vid"].iloc[0])
    sd = day.isoformat()
    start, end = base + float(plan.dep_sec[0]), base + float(plan.arr_sec[-1])
    events: dict[int, tuple] = {}
    for k in range(n):
        a = int(np.searchsorted(p, 2 * k, "left"))
        b = int(np.searchsorted(p, 2 * k, "right")) - 1
        arr = dep = arr_err = dep_err = np.nan
        if a <= b:  # observed at the stop
            interp = False
            if k > 0 and a > 0 and t[a] - t[a - 1] <= MAX_GAP_SEC:
                arr, arr_err = (t[a - 1] + t[a]) / 2, (t[a] - t[a - 1]) / 2
            if k < n - 1 and b + 1 < len(t) and t[b + 1] - t[b] <= MAX_GAP_SEC:
                dep, dep_err = (t[b] + t[b + 1]) / 2, (t[b + 1] - t[b]) / 2
            feed_delay = delay[a]
        else:       # passed between reports a-1 and a
            lo, hi = a - 1, a
            if lo < 0 or hi >= len(t) or t[hi] - t[lo] > MAX_GAP_SEC:
                continue
            interp = True
            s_lo = tt.report_s(geom, int(idx[lo]), bool(stopped[lo]), x[lo], y[lo])
            s_hi = tt.report_s(geom, int(idx[hi]), bool(stopped[hi]), x[hi], y[hi])
            s_k = float(geom.stop_s[k])
            frac = (s_k - s_lo) / (s_hi - s_lo) if s_hi > s_lo else 0.5
            arr = dep = t[lo] + float(np.clip(frac, 0.0, 1.0)) * (t[hi] - t[lo])
            arr_err = dep_err = (t[hi] - t[lo]) / 2
            feed_delay = delay[hi]
        if np.isnan(arr) and np.isnan(dep):
            continue
        s_arr, s_dep = base + float(plan.arr_sec[k]), base + float(plan.dep_sec[k])
        own = arr - s_arr if not np.isnan(arr) else dep - s_dep
        dwell = dep - arr if not interp and not (np.isnan(arr) or np.isnan(dep)) else np.nan
        events[k] = (sd, plan.trip_id, plan.route_id, plan.direction_id, vid, plan.stop_ids[k],
                     int(plan.seq[k]), k, n, s_arr, s_dep, arr, dep, arr_err, dep_err, dwell, own,
                     feed_delay, interp, arr if not np.isnan(arr) else dep, start, end, plan.shape_id,
                     plan.feed_version)
    segs = []
    for k in range(n - 1):
        e0, e1 = events.get(k), events.get(k + 1)
        if e0 is None or e1 is None or np.isnan(e0[12]) or np.isnan(e1[11]):
            continue
        dep0, arr1 = e0[12], e1[11]
        run = arr1 - dep0
        if run <= 0 or run > MAX_RUN_SEC:
            continue
        local = from_unix(dep0)
        segs.append((sd, plan.trip_id, plan.route_id, plan.direction_id, plan.shape_id,
                     plan.stop_ids[k], plan.stop_ids[k + 1], int(plan.seq[k]), int(plan.seq[k + 1]), k,
                     dep0, arr1, run, float(plan.arr_sec[k + 1] - plan.dep_sec[k]),
                     float(geom.stop_s[k + 1] - geom.stop_s[k]), local.hour, DAY_TYPES[local.weekday()],
                     e0[18], e1[18], plan.feed_version))
    return list(events.values()), segs


def compute(reports: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Stop events and segments of every trip run in `reports` (+ counts of what did not match)."""
    ev_rows: list[tuple] = []
    seg_rows: list[tuple] = []
    unmatched: set[str] = set()
    runs: dict[tuple[str, str], int] = {}
    if len(reports):
        reports = reports[reports["seq"] >= 0]
        for (trip, vid), g in reports.groupby(["trip", "vid"], sort=False):
            first = g.iloc[int(g["t"].to_numpy().argmin())]
            m = match_trip(str(trip), float(first["t"]), int(first["seq"]))
            if m is None:
                unmatched.add(str(trip))
                continue
            plan, day, base = m
            ev, sg = trip_events(g, plan, day, base)
            if ev:
                runs[(str(trip), day.isoformat())] = runs.get((str(trip), day.isoformat()), 0) + 1
            ev_rows.extend(ev)
            seg_rows.extend(sg)
    events = pd.DataFrame(ev_rows, columns=EVENT_COLUMNS)
    segments = pd.DataFrame(seg_rows, columns=SEGMENT_COLUMNS)
    # one trip, one service date, two vehicles (a hand-over or a data error): keep the vehicle seen most
    if len(events) and any(c > 1 for c in runs.values()):
        counts = events.groupby(["trip_id", "service_date", "vehicle_id"]).size().rename("n").reset_index()
        best = counts.sort_values("n", ascending=False).drop_duplicates(["trip_id", "service_date"])
        keep = set(zip(best["trip_id"], best["service_date"], best["vehicle_id"]))
        events = events[[k in keep for k in zip(events["trip_id"], events["service_date"], events["vehicle_id"])]]
    return events, segments, {"tripsNotInGtfs": len(unmatched)}


# --- the hour loop -----------------------------------------------------------------------------------

def manifest_path() -> Path:
    return out_dir() / "manifest.json"


def read_manifest() -> dict:
    try:
        return json.loads(manifest_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": VERSION, "hours": {}}


def _write_manifest(m: dict) -> None:
    p = manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(m, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def pending_hours(now_utc: datetime | None = None) -> list[tuple[Path, datetime]]:
    """Recording files whose hour can be built now and is not built yet, oldest first."""
    files = vehicles.recording_files()
    if len(files) < 1:
        return []
    built = read_manifest().get("hours", {})
    newest = vehicles.newest_snapshot()
    if newest is None:
        return []
    newest_t = vehicles.snapshot_time(newest)
    now_utc = now_utc or datetime.now(timezone.utc)
    stopped = (now_utc - newest_t).total_seconds() > 3600   # the recorder is off: build everything
    open_path = files[-1][0]
    out = []
    for path, hour in files:
        if stem(hour) in built:
            continue
        if path == open_path and not stopped:
            continue
        if not stopped and newest_t < hour + timedelta(hours=1, seconds=READY_AFTER_SEC):
            continue
        out.append((path, hour))
    return out


def build_hour(path: Path, hour: datetime, files: list[tuple[Path, datetime]]) -> dict:
    """Stage A + B for one hour; writes its events and segments and returns its manifest record."""
    by_hour = {h: p for p, h in files}
    open_path = files[-1][0]
    parts, stats = [], {}
    for h in (hour - timedelta(hours=1), hour, hour + timedelta(hours=1)):
        p = by_hour.get(h)
        if p is None:
            continue
        df, st = hour_reports(p, closed=p != open_path)
        parts.append(df)
        if h == hour:
            stats, own = st, df
    reports = pd.concat(parts, ignore_index=True).drop_duplicates(["vid", "t"])
    events, segments, extra = compute(reports)
    lo, hi = hour.timestamp(), (hour + timedelta(hours=1)).timestamp()
    events = events[(events["event_ts"] >= lo) & (events["event_ts"] < hi)]
    segments = segments[(segments["dep_ts"] >= lo) & (segments["dep_ts"] < hi)]
    s = stem(hour)
    _write(events, out_dir() / "events" / f"{s}.parquet")
    _write(segments, out_dir() / "segments" / f"{s}.parquet")
    return {
        "hour": iso(hour), "snapshots": stats.get("snapshots", 0), "first": stats.get("first"),
        "last": stats.get("last"), "reports": int(len(own)), "vehicles": sorted(set(own["vid"])), "gaps": stats.get("gaps", []),
        "routes": sorted(set(own["route"]) - {""}),
        "events": int(len(events)), "interpolated": int(events["interpolated"].sum()),
        "dwell": int(events["dwell_sec"].notna().sum()), "segments": int(len(segments)),
        "feedVersions": sorted({v for v in events["feed_version"].dropna()}),
        "tripsNotInGtfs": extra["tripsNotInGtfs"], "builtAt": iso(datetime.now(TZ)),
    }


_lock = threading.Lock()


def build(max_hours: int | None = None, verbose: bool = False) -> int:
    """Build every pending hour (at most `max_hours`); returns how many were built."""
    if not _lock.acquire(blocking=False):
        return 0
    try:
        todo = pending_hours()
        if max_hours is not None:
            todo = todo[:max_hours]
        files = vehicles.recording_files()
        done = 0
        for path, hour in todo:
            t0 = time.perf_counter()
            rec = build_hour(path, hour, files)
            m = read_manifest()
            m.setdefault("hours", {})[stem(hour)] = rec
            m["version"] = VERSION
            _write_manifest(m)
            done += 1
            if verbose:
                print(f"  {stem(hour)}: {rec['snapshots']} snapshots, {rec['reports']} reports, "
                      f"{rec['events']} stop events ({rec['interpolated']} interpolated), "
                      f"{rec['segments']} segments ({time.perf_counter() - t0:.1f} s)", flush=True)
        return done
    finally:
        _lock.release()


def build_in_background() -> bool:
    """Start a build thread when hours are pending and none runs; True if one was started."""
    if _lock.locked() or not pending_hours():
        return False
    threading.Thread(target=build, name="observed-build", daemon=True).start()
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the observed timetable (L0) from the vehicle recording.")
    ap.add_argument("--max-hours", type=int, default=None, help="build at most N pending hours")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    ensure_dirs()
    print(f"observed timetable v{VERSION} -> {out_dir()}", flush=True)
    n = build(args.max_hours, verbose=True)
    left = len(pending_hours())
    print(f"built {n} hour(s); {len(read_manifest().get('hours', {}))} built in all; {left} pending", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
