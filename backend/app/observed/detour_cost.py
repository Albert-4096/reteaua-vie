"""L1-B: what a closure's diversion costs in minutes, planned vs measured vs estimated.

For every line of the closure, the timetable before the closure (the newest GTFS that starts
before the closure, e.g. 4.29 in $DATA_DIR/gtfs-history/) is compared with the one in force when
it starts (4.30), trip by trip (SMTT keeps the trip ids). Each run of stops that changed is one
stretch, with the stop before and after it as anchors when the line keeps them:
`detour` (both anchors), `start_moved` / `end_moved` (the terminal moved), `truncated_start` /
`truncated_end` (the line now starts or ends at the anchor).

- planned:  scheduled time over the stretch, before and after, and after − before, per trip,
            over the trips that run on the recorded service days;
- measured: from L0, departure at the stretch's first stop to arrival at its last stop;
- estimated: what the method for a new closure would predict for the same stretch and hour:
            the stretch is cut into 20 m slices, each slice is matched to the OSM drive segment it
            runs on (app.m4_access.detour: 15 m, same rule as `routeIdsOnEdge`), and each segment
            gets the median pace (s/m) of the other lines' measured stop-to-stop runs on it in the
            same direction (±1 h of the trip's hour, else all hours, else the area around the
            stretch); plus the median dwell measured at the stretch's intermediate stops.
            Back-test: estimated − measured, trip by trip.

Every figure is a median with a 90 % bootstrap interval, one trip = one block (other lines' trips
are blocks too, for the estimate). Fewer than MIN_TRIPS trips → `conclusive: false`
(„neconcludent”). Measured on Fri afternoon + weekend only: never extrapolated to weekdays.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pandas as pd
from shapely import STRtree
from shapely.geometry import LineString, Point

from app.common import gtfs, state
from app.common import provenance as prov
from app.common.errors import not_found
from app.common.jobs import closure_fingerprint, respond
from app.common.geo import from_geojson, to_metric
from app.common.timeutil import from_unix, parse_iso
from app.config import TZ, get_settings
from app.models.base import I18n
from app.observed import store
from app.observed import timetable as tt
from app.observed.build import _timetable as timetable_day
from app.observed.models import (DetourCost, DetourHour, DetourStops, DetourStretch, DetourTotals, Estimate,
                                 PlannedTimes)

log = logging.getLogger("reteaua_vie.observed")

ALGO_VERSION = 1
MIN_TRIPS = 10        # fewer trips than this: „neconcludent”
MIN_OBS = 3           # fewer other-line runs than this on a street: fall back (all hours, then the area)
BOOT = 200
SEED = 20261114
SLICE_M = 20.0
AREA_M = 1500.0       # other lines' runs within this distance of the stretch form the area fallback
NEAR_M = 300.0        # a changed stretch counts for the closure when one of its stops is this close
DIR_COS = 0.5

METHOD = I18n(
    ro=("Planificat: orarul SMTT de dinainte de lucrare comparat cursă cu cursă cu cel în vigoare la începutul ei, pe "
        "porțiunea care s-a schimbat. Măsurat: din orarul observat (plecarea din prima stație a porțiunii → sosirea "
        "în ultima). Estimat: metoda pentru o lucrare nouă: viteza măsurată a altor linii pe aceleași străzi (OSM), "
        "la aceeași oră (±1 h), plus staționarea măsurată în stații. Mediane cu interval bootstrap 90 %, o cursă = un "
        f"bloc; sub {MIN_TRIPS} curse: „neconcludent”. Doar vineri după-amiază și weekend; fără extrapolare la zile "
        "lucrătoare."),
    en=("Planned: SMTT's timetable before the works compared trip by trip with the one in force when they start, on "
        "the stretch that changed. Measured: from the observed timetable (departure at the stretch's first stop → "
        "arrival at its last). Estimated: the method for a new closure: other lines' measured speed on the same "
        "streets (OSM), same hour (±1 h), plus measured dwell at stops. Medians with a 90 % bootstrap interval, one "
        f"trip = one block; under {MIN_TRIPS} trips: inconclusive. Friday afternoon and weekend only; no weekday "
        "extrapolation."),
)


# --- statistics --------------------------------------------------------------------------------

def _wmedian(x: np.ndarray, w: np.ndarray) -> float:
    w = np.asarray(w, dtype=int)
    if len(x) == 0 or w.sum() == 0:
        return float("nan")
    return float(np.median(np.repeat(x, w)))


def _estimate(point: float, boots: np.ndarray, n: int) -> Estimate:
    if n == 0 or np.isnan(point):
        return Estimate(sec=None, low=None, high=None, n=n, conclusive=False)
    b = boots[~np.isnan(boots)]
    lo, hi = (np.percentile(b, [5, 95]) if len(b) else (np.nan, np.nan))
    r = lambda v: None if np.isnan(v) else round(float(v), 1)  # noqa: E731
    return Estimate(sec=r(point), low=r(lo), high=r(hi), n=n, conclusive=n >= MIN_TRIPS)


def boot_median(x: np.ndarray, rng: np.random.Generator) -> Estimate:
    """Median of per-trip values with a block bootstrap (one value per trip, so blocks = values)."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return _estimate(float("nan"), np.zeros(0), 0)
    w = rng.poisson(1.0, size=(BOOT, len(x)))
    return _estimate(float(np.median(x)), np.array([_wmedian(x, wi) for wi in w]), len(x))


def _boot_paired(est_boot: np.ndarray, est: np.ndarray, meas: np.ndarray, rng: np.random.Generator
                 ) -> tuple[Estimate, Estimate]:
    """(estimated, estimated − measured) medians; est_boot[b] = per-trip estimates of replicate b."""
    ok = ~np.isnan(est) & ~np.isnan(meas)
    if not ok.any():
        e = _estimate(float("nan"), np.zeros(0), 0)
        return e, e
    est, meas, eb = est[ok], meas[ok], est_boot[:, ok]
    w = rng.poisson(1.0, size=(BOOT, len(est)))
    b_est = np.array([_wmedian(eb[i], w[i]) for i in range(BOOT)])
    b_err = np.array([_wmedian(eb[i] - meas, w[i]) for i in range(BOOT)])
    n = int(ok.sum())
    return _estimate(float(np.median(est)), b_est, n), _estimate(float(np.median(est - meas)), b_err, n)


# --- the timetables before and after --------------------------------------------------------------

def _history() -> list[Path]:
    d = get_settings().data_dir / "gtfs-history"
    return sorted(d.glob("*.zip")) if d.is_dir() else []


def _start(p: Path) -> date | None:
    st = p.stat()
    return gtfs._zip_meta(str(p), st.st_mtime, st.st_size)[1]


def feeds_for(closure: dict) -> tuple[Path | None, Path | None]:
    """(the version before, the timetable in force when the closure starts); before = the newest
    feed that started before the one in force (4.29 for Mocioni, whose diversion is in 4.30)."""
    day = parse_iso(closure["window"]["start"]).astimezone(TZ).date()
    paths = _history() + gtfs._candidates()
    after = gtfs.choose_feed(paths, day)
    if after is None:
        return None, None
    a_start = _start(after) or day
    earlier = [p for p in paths if (_start(p) or a_start) < a_start]
    before = gtfs.choose_feed(earlier, a_start - timedelta(days=1)) if earlier else None
    return before, after


def closure_routes(closure: dict) -> list[str]:
    ids = set(closure.get("routeIds") or []) | {a["routeId"] for a in closure.get("routeActions") or []}
    return sorted(ids)


def changed_blocks(a: tuple[str, ...], b: tuple[str, ...]) -> list[tuple[str, tuple[int, int], tuple[int, int]]]:
    """[(kind, (i0, i1), (j0, j1))]: stop index ranges (half-open, anchors included) in a and b."""
    ops = SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes()
    blocks: list[list[int]] = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            continue
        if blocks and blocks[-1][1] == i1 and blocks[-1][3] == j1:   # adjacent ops: one change
            blocks[-1][1], blocks[-1][3] = i2, j2
        else:
            blocks.append([i1, i2, j1, j2])
    out = []
    for i1, i2, j1, j2 in blocks:
        start = i1 > 0 and j1 > 0
        end = i2 < len(a) and j2 < len(b)
        ia, ib = (i1 - 1 if start else i1), (i2 + 1 if end else i2)
        ja, jb = (j1 - 1 if start else j1), (j2 + 1 if end else j2)
        if start and end:
            kind = "detour"
        elif not start:
            kind = "truncated_start" if j1 == j2 else "start_moved"
        else:
            kind = "truncated_end" if j1 == j2 else "end_moved"
        out.append((kind, (ia, ib), (ja, jb)))
    return out


@dataclass
class Stretch:
    route_id: str
    direction_id: int
    kind: str
    before: tuple[str, ...]
    after: tuple[str, ...]
    planned: list[tuple[str, str, float, float]] = field(default_factory=list)  # (trip, date, before s, after s)


def _span(plan: tt.TripPlan, i0: int, i1: int) -> float:
    return float(plan.arr_sec[i1 - 1] - plan.dep_sec[i0]) if i1 - i0 >= 2 else 0.0


def closure_stops(closure: dict, before: tt.Timetable) -> set[str]:
    """Stops the closure touches: those its route actions suspend, and those within NEAR_M of its geometry."""
    ids = {sid for a in closure.get("routeActions") or [] for sid in a.get("suspendedStopIds") or []}
    if closure.get("geometry"):
        zone = to_metric(from_geojson(closure["geometry"])).buffer(NEAR_M + float(closure.get("bufferMeters") or 0))
        ids |= {sid for sid, (x, y) in before.stop_xy.items() if zone.contains(Point(x, y))}
    return ids


def stretches(closure: dict, before: tt.Timetable, after: tt.Timetable, days: list[date]) -> list[Stretch]:
    """Changed stretches of the closure's lines that touch the closure (a change elsewhere in the
    same timetable, e.g. another works, is left out)."""
    routes = set(closure_routes(closure))
    touched = closure_stops(closure, before)
    out: dict[tuple, Stretch] = {}
    for tid, pa in after.trips.items():
        if pa.route_id not in routes:
            continue
        pb = before.trips.get(tid)
        if pb is None or pb.stop_ids == pa.stop_ids:
            continue
        run_days = [d for d in days if tt.runs_on(pa, d)] if days else [None]
        for kind, (i0, i1), (j0, j1) in changed_blocks(pb.stop_ids, pa.stop_ids):
            key = (pa.route_id, pa.direction_id, pb.stop_ids[i0:i1], pa.stop_ids[j0:j1])
            if not (set(key[2]) | set(key[3])) & touched:
                continue
            s = out.setdefault(key, Stretch(pa.route_id, pa.direction_id, kind, key[2], key[3]))
            for d in run_days:
                s.planned.append((tid, d.isoformat() if d else "", _span(pb, i0, i1), _span(pa, j0, j1)))
    return sorted(out.values(), key=lambda s: (s.route_id, s.direction_id, s.kind))


# --- measured, from L0 ------------------------------------------------------------------------------

def measured_runs(ev: pd.DataFrame, s: Stretch) -> pd.DataFrame:
    """Per recorded trip of the stretch's line: dep at its first stop, arr at its last, planned span."""
    if len(s.after) < 2 or not len(ev):
        return pd.DataFrame(columns=["trip_id", "service_date", "dep", "arr", "run", "planned", "hour", "day_type"])
    x = ev[(ev["route_id"] == s.route_id) & (ev["direction_id"] == s.direction_id)]
    a = x[x["stop_id"] == s.after[0]][["trip_id", "service_date", "stop_index", "dep", "sched_dep"]]
    b = x[x["stop_id"] == s.after[-1]][["trip_id", "service_date", "stop_index", "arr", "sched_arr"]]
    j = a.merge(b, on=["trip_id", "service_date"], suffixes=("_a", "_b"))
    j = j[j["stop_index_b"] - j["stop_index_a"] == len(s.after) - 1].dropna(subset=["dep", "arr"])
    j = j.assign(run=j["arr"] - j["dep"], planned=j["sched_arr"] - j["sched_dep"])
    j = j[j["run"] > 0].drop_duplicates(["trip_id", "service_date"])
    local = [from_unix(t) for t in j["dep"]]
    return j.assign(hour=[t.hour for t in local], day_type=[("mon", "tue", "wed", "thu", "fri", "sat", "sun")[t.weekday()]
                                                            for t in local])


# --- estimated, from other lines on the same streets --------------------------------------------------

@dataclass
class StreetObs:
    pace: np.ndarray    # s/m of each other-line run on the street, same direction (or a dwell, in s)
    hour: np.ndarray
    block: np.ndarray   # index of its (trip, service date)
    _sorted: dict = field(default_factory=dict, repr=False)

    def sorted_near(self, hour: int) -> list[tuple[np.ndarray, np.ndarray]]:
        """[(values, blocks) near the hour, (values, blocks) of all hours], each sorted by value."""
        if hour not in self._sorted:
            near = _hour_near(self.hour, hour) if len(self.hour) else np.zeros(0, dtype=bool)
            out = []
            for mask in (near, np.ones(len(self.pace), dtype=bool)):
                v, b = self.pace[mask], self.block[mask]
                order = np.argsort(v, kind="stable")
                out.append((v[order], b[order]))
            self._sorted[hour] = out
        return self._sorted[hour]


def _wmedian_sorted(v: np.ndarray, w: np.ndarray) -> float:
    """Median of `v` (sorted) repeated `w` times each; NaN under MIN_OBS weighted values."""
    tot = int(w.sum())
    if tot < MIN_OBS:
        return float("nan")
    c = np.cumsum(w)
    k1 = int(np.searchsorted(c, (tot - 1) // 2 + 1))
    k2 = int(np.searchsorted(c, tot // 2 + 1))
    return float(v[k1] + v[k2]) / 2


def _hour_near(h: np.ndarray, hour: int) -> np.ndarray:
    d = np.abs(h - hour)
    return np.minimum(d, 24 - d) <= 1


class StretchModel:
    """Per-slice street paces and stop dwells of other lines around one stretch; est(hour, weights)."""

    def __init__(self, path: list[LineString], mid_stops: list[str], own_routes: set[str],
                 seg: pd.DataFrame, ev: pd.DataFrame, blocks: dict[tuple[str, str], int]):
        from app.m4_access import detour

        self.blocks = blocks
        d = detour.drive_edges()
        tree = detour._drive_tree()
        # slices of the path -> OSM drive segment (nearest within 15 m, along it) and travel direction
        self.slice_len: list[float] = []
        self.slice_unit: list[int | None] = []
        unit_dir: dict[int, np.ndarray] = {}
        for line in path:
            n = max(1, int(round(line.length / SLICE_M)))
            step = line.length / n
            for k in range(n):
                s = (k + 0.5) * step
                p = line.interpolate(s)
                q0, q1 = line.interpolate(max(0.0, s - 5)), line.interpolate(min(line.length, s + 5))
                v = np.array([q1.x - q0.x, q1.y - q0.y])
                v = v / (np.linalg.norm(v) or 1.0)
                best, best_d = None, detour.ROUTE_NEAR_M
                for i in tree.query(p.buffer(detour.ROUTE_NEAR_M)):
                    e = LineString(d.xy[int(i)])
                    dist = e.distance(p)
                    if dist > best_d:
                        continue
                    t = e.project(p)
                    a, b = e.interpolate(max(0.0, t - 5)), e.interpolate(min(e.length, t + 5))
                    u = np.array([b.x - a.x, b.y - a.y])
                    if abs(float(np.dot(u, v))) < 0.7 * (np.linalg.norm(u) or 1.0):
                        continue
                    best, best_d = int(i), dist
                self.slice_len.append(step)
                self.slice_unit.append(best)
                if best is not None:
                    unit_dir[best] = unit_dir.get(best, 0) + v
        self.slice_len_arr = np.array(self.slice_len)
        # other lines' runs near the path, with their GTFS geometry
        bounds = LineString(np.vstack([np.asarray(g.coords) for g in path])).buffer(AREA_M)
        seg = seg[~seg["route_id"].isin(own_routes)]
        stop_xy = timetable_day(date.fromisoformat(seg["service_date"].iloc[0])).stop_xy if len(seg) else {}
        near = {sid for sid, (x, y) in stop_xy.items() if bounds.contains(Point(x, y))}
        seg = seg[seg["from_stop_id"].isin(near) | seg["to_stop_id"].isin(near)]
        geoms, idx_rows = [], []
        cache: dict[tuple, LineString | None] = {}
        for (tid, sd, fi), rows in seg.groupby(["trip_id", "service_date", "from_index"]).groups.items():
            plan = timetable_day(date.fromisoformat(sd)).trips.get(tid)
            if plan is None:
                continue
            key = (plan.pattern, int(fi))
            if key not in cache:
                g = tt.pattern_geometry(plan).segments[int(fi)]
                cache[key] = g if g.intersects(bounds) else None
            if cache[key] is not None:
                geoms.append(key)
                idx_rows.append(rows)
        uniq = sorted(set(geoms), key=str)
        gidx = {k: i for i, k in enumerate(uniq)}
        glines = [cache[k] for k in uniq]
        rows_by_g: dict[int, list] = {}
        for k, rows in zip(geoms, idx_rows):
            rows_by_g.setdefault(gidx[k], []).extend(rows)
        self.routes_used: set[str] = set()

        def obs_of(gs: list[int]) -> StreetObs:
            r = seg.loc[[i for g in gs for i in rows_by_g.get(g, [])]]
            r = r[(r["dist_m"] > 0) & (r["run_sec"] > 0)]
            return StreetObs(pace=(r["run_sec"] / r["dist_m"]).to_numpy(float), hour=r["hour_local"].to_numpy(int),
                             block=np.array([blocks.setdefault((t, s_), len(blocks))
                                             for t, s_ in zip(r["trip_id"], r["service_date"])], dtype=int)), r

        self.area, _ = obs_of(list(range(len(glines))))
        gtree = STRtree(glines) if glines else None
        self.units: dict[int, StreetObs] = {}
        for u, vsum in unit_dir.items():
            e = LineString(d.xy[u])
            zone = e.buffer(detour.ROUTE_NEAR_M)
            need = min(detour.ROUTE_MIN_M, 0.8 * e.length)
            v = vsum / (np.linalg.norm(vsum) or 1.0)
            mid = e.interpolate(0.5, normalized=True)
            hits = []
            for gi in (gtree.query(zone) if gtree is not None else []):
                g = glines[int(gi)]
                if g.intersection(zone).length < need:
                    continue
                t = g.project(mid)
                a, b = g.interpolate(max(0.0, t - 5)), g.interpolate(min(g.length, t + 5))
                w = np.array([b.x - a.x, b.y - a.y])
                if float(np.dot(w, v)) < DIR_COS * (np.linalg.norm(w) or 1.0):
                    continue          # the other line runs the other way on this street
                hits.append(int(gi))
            obs, r = obs_of(hits)
            self.units[u] = obs
            self.routes_used |= set(r["route_id"])
        # dwell at the stretch's intermediate stops, measured on other lines
        other = ev[~ev["route_id"].isin(own_routes) & ev["dwell_sec"].notna()]
        self.dwell: list[StreetObs] = []
        for sid in mid_stops:
            r = other[other["stop_id"] == sid]
            hours = np.array([from_unix(t).hour for t in r["arr"]], dtype=int)
            self.dwell.append(StreetObs(pace=r["dwell_sec"].to_numpy(float), hour=hours,
                                        block=np.array([blocks.setdefault((t, s_), len(blocks))
                                                        for t, s_ in zip(r["trip_id"], r["service_date"])], dtype=int)))
        area_stops = set(seg["from_stop_id"]) | set(seg["to_stop_id"])
        r = other[other["stop_id"].isin(area_stops)]
        self.area_dwell = StreetObs(pace=r["dwell_sec"].to_numpy(float),
                                    hour=np.array([from_unix(t).hour for t in r["arr"]], dtype=int),
                                    block=np.zeros(len(r), dtype=int))
        covered = [u is not None and len(self.units.get(u, StreetObs(np.zeros(0), np.zeros(0), np.zeros(0))).pace)
                   >= MIN_OBS for u in self.slice_unit]
        total = float(self.slice_len_arr.sum())
        self.coverage = round(float(self.slice_len_arr[np.array(covered, dtype=bool)].sum()) / total, 3) if total else None

    @staticmethod
    def _pick(o: StreetObs, hour: int, w: np.ndarray | None) -> float:
        """Median of o near `hour` (±1 h), else over all hours; NaN when too few runs."""
        for vals, blk in o.sorted_near(hour):
            ww = np.ones(len(vals), dtype=int) if w is None else w[blk]
            m = _wmedian_sorted(vals, ww)
            if not np.isnan(m):
                return m
        return float("nan")

    def estimate(self, hour: int, w: np.ndarray | None = None) -> float:
        area = self._pick(self.area, hour, w)
        cache: dict[int | None, float] = {}
        total = 0.0
        for length, u in zip(self.slice_len, self.slice_unit):
            if u not in cache:
                p = self._pick(self.units[u], hour, w) if u is not None and u in self.units else float("nan")
                cache[u] = area if np.isnan(p) else p
            total += length * cache[u]
        area_dwell = self._pick(self.area_dwell, hour, None)
        for o in self.dwell:
            dw = self._pick(o, hour, w)
            total += area_dwell if np.isnan(dw) else dw
        return total


def _path(s: Stretch, ev: pd.DataFrame, days: list[date]) -> list[LineString] | None:
    """The in-force GTFS shape between the stretch's first and last stop (one trip's pattern)."""
    for d in days:
        for tid in {t for t, sd, *_ in s.planned if sd == d.isoformat()}:
            plan = timetable_day(d).trips.get(tid)
            if plan is None:
                continue
            ids = plan.stop_ids
            for k in range(len(ids) - len(s.after) + 1):
                if ids[k:k + len(s.after)] == s.after:
                    segs = tt.pattern_geometry(plan).segments
                    return list(segs[k:k + len(s.after) - 1])
    return None


# --- the response -------------------------------------------------------------------------------------

def _names(tt_: tt.Timetable, ids: tuple[str, ...]) -> list[str]:
    return [tt_.stop_names.get(i, i) for i in ids]


def _short_names(sha: str) -> dict[str, str]:
    r = gtfs._FEEDS[sha].routes
    return dict(zip(r["route_id"], r.get("route_short_name", r["route_id"])))


def _recorded_days(ev: pd.DataFrame) -> list[date]:
    return sorted({date.fromisoformat(d) for d in ev["service_date"].unique()}) if len(ev) else []


def _overlaps(closure: dict, cov: dict | None) -> bool:
    if cov is None:
        return False
    s, e = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    return cov["first"] < e and cov["last"] > s


def _min(sec: float | None) -> str:
    return "—" if sec is None else f"{abs(sec) / 60:.1f}".replace(".", ",")


def _interval(e: Estimate) -> tuple[str, str]:
    if e.low is None or e.high is None:
        return "", ""
    f = lambda v: f"{v / 60:+.1f}".replace(".", ",").replace("-", "−")  # noqa: E731
    return f"; interval 90 %: {f(e.low)} … {f(e.high)} min", f"; 90 % interval: {f(e.low)} … {f(e.high)} min"


def _finding(rows: list[DetourStretch], totals: DetourTotals) -> I18n | None:
    """One plain sentence per figure, from the totals (all trips of all stretches)."""
    if not rows:
        return None
    extra = totals.plannedExtra
    moved = {r.kind for r in rows} <= {"start_moved", "end_moved", "truncated_start", "truncated_end"}
    routes = ", ".join(sorted({r.shortName for r in rows}))
    if extra.sec is None:
        return None
    if moved and extra.sec <= 0:
        ro = (f"Orarul nu adaugă minute de ocolire: mută capătul liniilor {routes}. Pe porțiunile schimbate, cursele "
              f"sunt planificate cu {_min(extra.sec)} min mai scurt (mediana, {extra.n} de curse).")
        en = (f"The timetable adds no detour minutes: it moves the terminal of lines {routes}. On the changed "
              f"stretches trips are planned {_min(extra.sec)} min shorter (median, {extra.n} trips).")
    else:
        more = "mai mult" if extra.sec > 0 else "mai puțin"
        ro = (f"Pe porțiunile ocolite, orarul liniilor {routes} are cu {_min(extra.sec)} min {more} "
              f"(mediana, {extra.n} de curse).")
        en = (f"On the detour stretches, lines {routes} are planned {_min(extra.sec)} min "
              f"{'longer' if extra.sec > 0 else 'shorter'} (median, {extra.n} trips).")
    mvp = totals.measuredVsPlanned
    if mvp.n and mvp.sec is not None:
        i_ro, i_en = _interval(mvp)
        side_ro, side_en = ("mai repede decât", "faster than") if mvp.sec < 0 else ("mai încet decât", "slower than")
        tail_ro = "" if mvp.conclusive else ", neconcludent"
        tail_en = "" if mvp.conclusive else ", inconclusive"
        ro += (f" Pe porțiunile noi, cursele înregistrate au mers cu {_min(mvp.sec)} min {side_ro} orarul "
               f"({mvp.n} de curse{i_ro}{tail_ro}).")
        en += (f" On the new stretches, recorded trips ran {_min(mvp.sec)} min {side_en} the timetable "
               f"({mvp.n} trips{i_en}{tail_en}).")
    err = totals.estimateError
    if err.n and err.sec is not None:
        i_ro, i_en = _interval(err)
        side_ro, side_en = ("sub", "below") if err.sec < 0 else ("peste", "above")
        tail_ro = "" if err.conclusive else ", neconcludent"
        tail_en = "" if err.conclusive else ", inconclusive"
        ro += (f" Estimarea din vitezele altor linii pe aceleași străzi a fost cu {_min(err.sec)} min {side_ro} "
               f"timpul măsurat ({err.n} de curse{i_ro}{tail_ro}).")
        en += (f" The estimate from other lines' speeds on the same streets was {_min(err.sec)} min {side_en} "
               f"the measured time ({err.n} trips{i_en}{tail_en}).")
    return I18n(ro=ro, en=en)


def compute_detour_cost(closure: dict) -> DetourCost:
    rng = np.random.default_rng(SEED)
    cid = closure.get("id") or ""
    before_p, after_p = feeds_for(closure)
    cov = store.coverage()
    label = I18n(ro=cov["labelRo"], en=cov["labelEn"]) if cov else None
    empty = DetourTotals(plannedExtra=_estimate(float("nan"), np.zeros(0), 0),
                         measuredVsPlanned=_estimate(float("nan"), np.zeros(0), 0),
                         estimateError=_estimate(float("nan"), np.zeros(0), 0))
    provs = []
    if before_p is None or after_p is None or before_p == after_p:
        return DetourCost(closureId=cid, status="fara_orar_vechi", label=label, finding=None, minTrips=MIN_TRIPS,
                          feedBefore=None, feedAfter=None, stretches=[], totals=empty, method=METHOD, provenance=provs)
    before, after = tt.timetable_for(before_p), tt.timetable_for(after_p)
    provs += [gtfs._FEEDS[before.sha].provenance.model_copy(update={"note": "orarul de dinainte de lucrare / before"}),
              gtfs._FEEDS[after.sha].provenance.model_copy(update={"note": "orarul de la începutul lucrării / after"})]
    recorded = _overlaps(closure, cov)
    ev = store.events() if recorded else store.events().iloc[0:0]
    seg = store.segments() if recorded else store.segments().iloc[0:0]
    days = _recorded_days(ev)
    rows_s = stretches(closure, before, after, days)
    if not rows_s:
        return DetourCost(closureId=cid, status="fara_schimbare", label=label, finding=None, minTrips=MIN_TRIPS,
                          feedBefore=before.version, feedAfter=after.version, stretches=[], totals=empty,
                          method=METHOD, provenance=provs)
    own = set(closure_routes(closure))
    names = _short_names(after.sha)
    blocks: dict[tuple[str, str], int] = {}
    out_rows: list[DetourStretch] = []
    pool = {"extra": [], "mvp": [], "est": [], "meas": [], "boot": []}
    models: list[tuple[Stretch, pd.DataFrame, StretchModel | None]] = []
    for s in rows_s:
        runs = measured_runs(ev, s)
        model = None
        if len(s.after) >= 2 and len(runs):
            path = _path(s, ev, days)
            if path:
                model = StretchModel(path, list(s.after[1:-1]), own, seg, ev, blocks)
        models.append((s, runs, model))
    # one set of bootstrap weights over every other-line trip, shared by all stretches (pooled totals)
    w_other = rng.poisson(1.0, size=(BOOT, max(1, len(blocks))))
    for s, runs, model in models:
        pl = pd.DataFrame(s.planned, columns=["trip", "date", "before", "after"])
        extra = (pl["after"] - pl["before"]).to_numpy(float)
        planned = PlannedTimes(before=boot_median(pl["before"].to_numpy(float), rng),
                               after=boot_median(pl["after"].to_numpy(float), rng),
                               extra=boot_median(extra, rng))
        pool["extra"].append(extra)
        measured = mvp = est_e = err_e = None
        by_hour: list[DetourHour] = []
        if len(s.after) >= 2:
            meas = runs["run"].to_numpy(float)
            measured = boot_median(meas, rng)
            mvp_v = (runs["run"] - runs["planned"]).to_numpy(float)
            mvp = boot_median(mvp_v, rng)
            pool["mvp"].append(mvp_v)
            hours = runs["hour"].to_numpy(int)
            est = np.array([model.estimate(int(h)) for h in hours]) if model else np.full(len(runs), np.nan)
            if model is not None and len(runs):
                uh, inv = np.unique(hours, return_inverse=True)
                eb = np.array([[model.estimate(int(h), w_other[b]) for h in uh] for b in range(BOOT)])[:, inv]
            else:
                eb = np.full((BOOT, len(runs)), np.nan)
            est_e, err_e = _boot_paired(eb, est, meas, rng)
            pool["est"].append(est)
            pool["meas"].append(meas)
            pool["boot"].append(eb)
            for (h, dt), g in runs.assign(est=est).groupby(["hour", "day_type"]):
                by_hour.append(DetourHour(hour=int(h), dayType=str(dt), n=len(g),
                                          measuredSec=round(float(g["run"].median()), 1),
                                          estimatedSec=None if g["est"].isna().all() else round(float(g["est"].median()), 1)))
        out_rows.append(DetourStretch(
            routeId=s.route_id, shortName=str(names.get(s.route_id, s.route_id)), directionId=s.direction_id,
            kind=s.kind, before=DetourStops(stopIds=list(s.before), stopNames=_names(before, s.before)),
            after=DetourStops(stopIds=list(s.after), stopNames=_names(after, s.after)),
            planned=planned, measured=measured, measuredVsPlanned=mvp, estimated=est_e, estimateError=err_e,
            coverage=model.coverage if model else None,
            otherRoutes=sorted(model.routes_used) if model else [], byHour=by_hour))
    cat = lambda k: np.concatenate(pool[k]) if pool[k] else np.zeros(0)  # noqa: E731
    _e, err_total = (_boot_paired(np.concatenate(pool["boot"], axis=1), cat("est"), cat("meas"), rng)
                     if pool["boot"] else (None, _estimate(float("nan"), np.zeros(0), 0)))
    totals = DetourTotals(plannedExtra=boot_median(cat("extra"), rng), measuredVsPlanned=boot_median(cat("mvp"), rng),
                          estimateError=err_total)
    if recorded and cov:
        provs.append(prov.vehicles_provenance(cov["last"], f"{cov['labelRo']}; orarul observat (L0)"))
        from app.m1_disruption.impact import osm_provenance
        provs.append(osm_provenance("străzile pe care merg alte linii / streets other lines run on"))
    return DetourCost(closureId=cid, status="ok" if recorded else "fara_inregistrare", label=label if recorded else None,
                      finding=_finding(out_rows, totals), minTrips=MIN_TRIPS, feedBefore=before.version,
                      feedAfter=after.version, stretches=out_rows, totals=totals, method=METHOD, provenance=provs)


def job_key(closure_id: str) -> str:
    return (f"detour-cost:v{ALGO_VERSION}:{closure_id}:{closure_fingerprint(closure_id)}:"
            f"{len(store.built_stems())}:{(store.built_stems() or [''])[-1]}")


def respond_for(closure_id: str):
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id}.")
    return respond(job_key(closure_id), lambda: compute_detour_cost(closure))
