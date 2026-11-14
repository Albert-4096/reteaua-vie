"""The planned side of L0: GTFS trips, their stop times and stop positions along the shape.

`plan_for(trip_id, day)` gives the trip as the feed in force on that service date plans it.
Stop positions are metres along the trip's GTFS shape (projected in order, so a loop that
passes a stop twice keeps the right pass); a trip without a shape uses the straight line
through its stops.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString, Point
from shapely.ops import substring

from app.common import gtfs
from app.common.geo import project_lonlats
from app.common.timeutil import gtfs_service_start


@dataclass(frozen=True)
class TripPlan:
    trip_id: str
    route_id: str
    direction_id: int
    service_id: str
    shape_id: str
    seq: np.ndarray          # GTFS stop_sequence, ascending
    stop_ids: tuple[str, ...]
    arr_sec: np.ndarray      # seconds since the service day's 'noon minus 12 h' (may pass 86400)
    dep_sec: np.ndarray
    feed_version: str | None
    feed_sha: str

    @property
    def pattern(self) -> tuple[str, str, tuple[str, ...]]:
        return (self.feed_sha, self.shape_id, self.stop_ids)


@dataclass(frozen=True)
class Timetable:
    sha: str
    version: str | None
    trips: dict[str, TripPlan]
    stop_xy: dict[str, tuple[float, float]]       # stop_id -> UTM metres
    shapes: dict[str, LineString]                 # shape_id -> UTM metres


def _read_shapes(path: str) -> dict[str, LineString]:
    with zipfile.ZipFile(path) as z:
        if "shapes.txt" not in z.namelist():
            return {}
        df = pd.read_csv(io.BytesIO(z.read("shapes.txt")), dtype={"shape_id": str})
    df = df.sort_values(["shape_id", "shape_pt_sequence"])
    xy = project_lonlats(zip(df["shape_pt_lon"].to_numpy(float), df["shape_pt_lat"].to_numpy(float)))
    out: dict[str, LineString] = {}
    ids = df["shape_id"].to_numpy()
    cuts = np.flatnonzero(ids[1:] != ids[:-1]) + 1
    for lo, hi in zip(np.r_[0, cuts], np.r_[cuts, len(ids)]):
        if hi - lo >= 2:
            out[str(ids[lo])] = LineString(xy[lo:hi])
    return out


@lru_cache(maxsize=4)
def _timetable(sha: str) -> Timetable:
    f = gtfs._FEEDS[sha]
    st = f.stop_times.sort_values(["trip_id", "stop_sequence"])
    trips = f.trips.set_index("trip_id")
    tid = st["trip_id"].to_numpy()
    seq = st["stop_sequence"].to_numpy(int)
    sid = st["stop_id"].to_numpy()
    arr = st["arr_sec"].to_numpy(int)
    dep = st["dep_sec"].to_numpy(int)
    cuts = np.flatnonzero(tid[1:] != tid[:-1]) + 1
    plans: dict[str, TripPlan] = {}
    for lo, hi in zip(np.r_[0, cuts], np.r_[cuts, len(tid)]):
        t = str(tid[lo])
        if t not in trips.index:
            continue
        row = trips.loc[t]
        plans[t] = TripPlan(
            trip_id=t, route_id=str(row["route_id"]), direction_id=int(row["direction_id"]),
            service_id=str(row["service_id"]), shape_id=str(row.get("shape_id") or ""),
            seq=seq[lo:hi], stop_ids=tuple(str(s) for s in sid[lo:hi]),
            arr_sec=arr[lo:hi], dep_sec=dep[lo:hi], feed_version=f.version, feed_sha=sha)
    stops = f.stops
    xy = project_lonlats(zip(stops["stop_lon"].astype(float), stops["stop_lat"].astype(float)))
    stop_xy = {str(s): (float(x), float(y)) for s, (x, y) in zip(stops["stop_id"], xy)}
    return Timetable(sha=sha, version=f.version, trips=plans, stop_xy=stop_xy, shapes=_read_shapes(str(f.path)))


def timetable_on(day: date) -> Timetable:
    """The timetable of the feed in force on a service date."""
    return _timetable(gtfs.feed(at=day).sha256)


def runs_on(plan: TripPlan, day: date) -> bool:
    return plan.service_id in gtfs._service_dates(plan.feed_sha).get(day, frozenset())


def service_base(day: date) -> float:
    """Unix seconds of the service day's 'noon minus 12 h' (GTFS time zero)."""
    return gtfs_service_start(day).timestamp()


# --- positions along the shape ---------------------------------------------------------------

@dataclass(frozen=True)
class PatternGeometry:
    stop_s: np.ndarray               # metres along the line, one per stop, non-decreasing
    segments: tuple[LineString, ...]  # line between stop i and stop i+1 (len = stops - 1)


_GEOM: dict[tuple, PatternGeometry] = {}


def pattern_geometry(plan: TripPlan) -> PatternGeometry:
    key = plan.pattern
    g = _GEOM.get(key)
    if g is not None:
        return g
    tt = _timetable(plan.feed_sha)
    pts = [tt.stop_xy.get(s) for s in plan.stop_ids]
    known = [p for p in pts if p is not None]
    line = tt.shapes.get(plan.shape_id)
    if line is None or line.length < 1:
        line = LineString(known) if len(known) >= 2 else LineString([(0, 0), (1, 0)])
    total = line.length
    stop_s = np.zeros(len(pts))
    prev = 0.0
    for i, p in enumerate(pts):
        if p is None:
            stop_s[i] = prev
            continue
        # search forward from the previous stop only, within a window, so a loop keeps the right pass
        straight = 0.0 if i == 0 or pts[i - 1] is None else float(np.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1]))
        hi = min(total, prev + max(1500.0, 4.0 * straight))
        part = substring(line, prev, hi) if hi > prev else None
        if part is None or part.length == 0 or part.geom_type != "LineString":
            s = prev
        else:
            s = prev + part.project(Point(p))
        stop_s[i] = s
        prev = s
    segs = []
    for i in range(len(pts) - 1):
        a, b = stop_s[i], stop_s[i + 1]
        seg = substring(line, a, b) if b > a else None
        if seg is None or seg.geom_type != "LineString" or seg.length == 0:
            pa, pb = pts[i] or (0.0, 0.0), pts[i + 1] or (0.0, 0.0)
            seg = LineString([pa, pb]) if pa != pb else LineString([pa, (pa[0] + 0.01, pa[1])])
        segs.append(seg)
    g = PatternGeometry(stop_s=stop_s, segments=tuple(segs))
    if len(_GEOM) > 4000:
        _GEOM.clear()
    _GEOM[key] = g
    return g


def report_s(geom: PatternGeometry, idx: int, stopped: bool, x: float, y: float) -> float:
    """Metres along the line of a report: at stop `idx` if stopped, else between idx-1 and idx."""
    if stopped or idx == 0:
        return float(geom.stop_s[idx])
    seg = geom.segments[idx - 1]
    lo, hi = float(geom.stop_s[idx - 1]), float(geom.stop_s[idx])
    s = lo + float(shapely.line_locate_point(seg, Point(x, y)))
    return min(max(s, lo), hi)
