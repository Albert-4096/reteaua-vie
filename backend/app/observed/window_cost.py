"""L2: the closure's windows priced by measured traffic (GET /api/closures/{id}/windows/measured).

For each line of the closure (its lost stop rows, as /windows counts them), on the stop order of the
timetable in force before the works: every run of lost stops with a served stop before it (A) and
after it (B) is a cut stretch. A cut at a terminal has no detour (the line is shortened: see
/detour-cost).

- Detour path: the shortest path from A to B on the OSM drive graph within 2 km of the closure
  (app.m4_access.detour.build_subgraph, oneways kept, the segments inside the closure removed). A
  street that no bus or trolleybus line runs on weighs BUS_FACTOR times its length, so the detour
  keeps to the streets public transport already uses. Deterministic (fixed graph order), cached.
- Minutes on it, per recorded day type and hour: the median pace of other lines' measured runs on
  the same OSM segments, same direction, ±1 h (app.observed.detour_cost.match_streets). A street with
  no measured bus gets no number; an hour under MIN_COVERAGE of the detour length measured has no
  time. The rest of a covered path runs at the covered part's mean pace.
- Normal minutes: the line's own measured runs A → B at that day type and hour; else the same
  street estimate on its GTFS shape.
- Window cost: departures lost (the /windows count) and detour vehicle-minutes = Σ trips at A ×
  (detour − normal) at that weekday and hour. The measured order ranks by vehicle-minutes, then
  departures lost; the two are not added (different units). A window with trips at a weekday and
  hour we did not record (Mon–Thu, Friday before 13:47) has no measured cost: no extrapolation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import networkx as nx
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString

from app.common import provenance as prov
from app.common.city import load_network
from app.common.geo import from_geojson, to_geojson, to_metric, to_wgs84
from app.common.jobs import closure_fingerprint
from app.common.timeutil import from_unix, iso
from app.config import TZ
from app.m1_disruption import impact as imp
from app.m4_access import windows as win
from app.models.base import I18n
from app.observed import detour_cost as dc
from app.observed import store
from app.observed.build import _timetable as timetable_day
from app.observed.models import (DetourHourCost, DetourLine, DetourStreet, MeasuredWindow, MeasuredWindows)

log = logging.getLogger("reteaua_vie.observed")

ALGO_VERSION = 2
MIN_COVERAGE = 0.8
MIN_TRIP_SHARE = 0.8   # a window is priced when this share of its detoured trips is at a measured weekday/hour
BUS_FACTOR = 2.0
SNAP_M = 150.0
SNAP_K = 6
BOOT = 200
SEED = 20261115
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MODES = {"R_TV": "tramvai", "R_TB": "troleibuz"}

METHOD = I18n(
    ro=("Ocolirea fiecărei linii: drumul cel mai scurt pe străzile OSM din jurul lucrării, de la ultima stație "
        "deservită dinaintea porțiunii închise la prima de după ea, fără străzile închise; străzile fără linie de "
        f"autobuz sau troleibuz contează de {BUS_FACTOR:.0f} ori lungimea lor. Minutele pe ocolire: viteza măsurată a "
        "altor linii pe aceleași străzi, în același sens, aceeași zi a săptămânii și oră (±1 h); o stradă fără "
        f"autobuz măsurat nu primește cifră, iar sub {MIN_COVERAGE:.0%} din lungime măsurată ora e „neconcludentă”. "
        "Minutele normale: cursele măsurate ale liniei pe porțiunea închisă. Costul unei ferestre: plecările pierdute "
        "(ca în lista ferestrelor) și minutele de vehicul în plus (curse × minute în plus); ordinea după trafic e "
        "după minute, apoi după plecări. Fără cost pe zilele și orele pe care nu le-am înregistrat (zile lucrătoare)."
        ).replace("80%", "80 %"),
    en=("Each line's detour: the shortest path on the OSM streets around the works, from the last served stop "
        "before the closed stretch to the first after it, without the closed streets; streets with no bus or "
        f"trolleybus line count {BUS_FACTOR:.0f} times their length. Minutes on the detour: other lines' measured "
        "speed on the same streets, same direction, weekday and hour (±1 h); a street with no measured bus gets no "
        f"number, and under {MIN_COVERAGE:.0%} of the length measured the hour is inconclusive. Normal minutes: the "
        "line's measured trips over the closed stretch. A window's cost: departures lost (as in the window list) "
        "and the added vehicle-minutes (trips × extra minutes); the traffic order ranks by minutes, then "
        "departures. No cost on weekdays and hours we did not record."),
)


NOTES = {
    "fara_inregistrare": I18n(ro="Orarul observat nu are încă nicio oră înregistrată.",
                              en="The observed timetable has no recorded hour yet."),
    "fara_ocolire": I18n(
        ro=("Nicio linie nu are stații deservite de ambele părți ale porțiunii închise: liniile sunt scurtate sau "
            "suspendate, deci nu au ocolire de măsurat (pentru o deviere deja în orar, vezi costul devierii)."),
        en=("No line has served stops on both sides of the closed stretch: lines are shortened or suspended, so there "
            "is no detour to price (for a diversion already in the timetable, see the detour cost).")),
    "neconcludent": I18n(ro=f"Nicio ocolire nu are autobuze măsurate pe cel puțin {MIN_COVERAGE:.0%} din lungime."
                         .replace("%", " %"),
                         en=f"No detour has measured buses on at least {MIN_COVERAGE:.0%} of its length."),
    "fara_ore": I18n(ro=("Nicio fereastră din intervalul căutat nu cade destul în zilele și orele înregistrate "
                         "(vineri după-amiază, weekend): nu extrapolăm la zile lucrătoare."),
                     en=("No window in the search range falls enough on the recorded days and hours (Friday afternoon, "
                         "weekend): we do not extrapolate to weekdays.")),
}


# --- cut stretches ---------------------------------------------------------------------------------

@dataclass
class Cut:
    route_id: str
    direction_id: int
    a: str
    b: str
    cut: list[str]
    order: list[str]


def _lost(analysis: dict) -> dict[tuple[str, int], set[str]]:
    lost: dict[tuple[str, int], set[str]] = {}
    for r in analysis.get("stops") or []:
        if imp.counts_as_lost(r):
            lost.setdefault((r["routeId"], int(r.get("directionId") or 0)), set()).add(str(r["stopId"]))
    return lost


def _runs(order: list[str], lost: set[str], blocked_segs: set[int], route: str, d: int,
          cuts: list[Cut], terminal: list[tuple[str, int]]) -> None:
    """Contiguous blocked stop-to-stop segments (geometric, or next to a lost stop) -> cuts."""
    segs = set(blocked_segs)
    for i, sid in enumerate(order):
        if sid in lost:
            segs |= {i - 1, i}
    segs = {k for k in segs if 0 <= k < len(order) - 1} | ({-1} if order and order[0] in lost else set()) \
        | ({len(order) - 1} if order and order[-1] in lost else set())
    for k0 in sorted(segs):
        if k0 - 1 in segs:
            continue
        k1 = k0
        while k1 + 1 in segs:
            k1 += 1
        a, b = k0, k1 + 1
        if a < 0 or b > len(order) - 1:
            terminal.append((route, d))
        else:
            cuts.append(Cut(route, d, order[a], order[b], order[a + 1:b], order))


def _closure_line(closure: dict):
    g = to_metric(from_geojson(closure["geometry"]))
    return g


def _passing(closure: dict, plan) -> set[int]:
    """Stop-to-stop segments of a trip pattern that run along the closed street in a closed direction."""
    line = _closure_line(closure)
    zone = line.buffer(float(closure.get("bufferMeters") or 30))
    need = min(50.0, 0.8 * line.length) if line.length > 0 else 1.0
    direction = closure.get("direction") or "both"
    parts = list(line.geoms) if hasattr(line, "geoms") else [line]
    out = set()
    for k, seg in enumerate(dc.tt.pattern_geometry(plan).segments):
        if not seg.intersects(zone) or seg.intersection(zone).length < need:
            continue
        part = min(parts, key=lambda p_: p_.distance(seg))
        mid = part.interpolate(0.5, normalized=True)
        t = seg.project(mid)
        a, b = seg.interpolate(max(0.0, t - 5)), seg.interpolate(min(seg.length, t + 5))
        tp = part.project(mid)
        c0, c1 = part.interpolate(max(0.0, tp - 5)), part.interpolate(min(part.length, tp + 5))
        u = np.array([b.x - a.x, b.y - a.y])
        v = np.array([c1.x - c0.x, c1.y - c0.y])
        cos = float(np.dot(u, v)) / ((np.linalg.norm(u) * np.linalg.norm(v)) or 1.0)
        if (direction == "along" and cos >= 0.7) or (direction == "against" and cos <= -0.7) \
                or (direction not in ("along", "against") and abs(cos) >= 0.7):
            out.add(k)
    return out


def cuts_for(closure: dict, analysis: dict, ttb: imp.Timetable, day: date) -> tuple[list[Cut], list[tuple[str, int]]]:
    """(cut stretches with a served stop on both sides, lines cut at a terminal).

    A timetable that already carries the diversion (an older timetable is the 'before', e.g. Mocioni):
    only the lost stops of the analysis, on the before-works stop order. Otherwise (the hero, a drawn
    section): also every bus or trolleybus pattern in force that runs along the closed street in a
    closed direction (≥ 50 m, or 80 % of a shorter closure, within its buffer), lost stop or not.
    """
    lost = _lost(analysis)
    cuts: list[Cut] = []
    terminal: list[tuple[str, int]] = []
    if ttb.history or not closure.get("geometry"):
        for (route, d), stops in sorted(lost.items()):
            _runs(ttb.stop_order(route, d), stops, set(), route, d, cuts, terminal)
        return cuts, terminal
    from collections import Counter

    counts: dict[tuple[str, int], Counter] = {}
    plans: dict[tuple[str, int, tuple], object] = {}
    for plan in timetable_day(day).trips.values():
        key = (plan.route_id, plan.direction_id)
        counts.setdefault(key, Counter())[plan.stop_ids] += 1
        plans.setdefault((plan.route_id, plan.direction_id, plan.stop_ids), plan)
    for (route, d), cnt in sorted(counts.items()):
        stops_ = cnt.most_common(1)[0][0]
        plan = plans[(route, d, stops_)]
        blocked = set() if route.startswith("R_TV") else _passing(closure, plan)
        mine = lost.get((route, d), set())
        if blocked or mine & set(stops_):
            _runs(list(stops_), mine, blocked, route, d, cuts, terminal)
    return cuts, terminal


# --- the detour path on the drive graph -------------------------------------------------------------

@dataclass
class Graph:
    g: nx.DiGraph
    node_xy: dict[int, tuple[float, float]]
    nodes: np.ndarray
    xy: np.ndarray


_GRAPHS: dict[str, Graph] = {}


def _bus_segments(seg_idx: list[int]) -> set[int]:
    """Drive segments a bus or trolleybus line runs on: >= 80 % of points every 10 m within 15 m of a line."""
    from app.m4_access import detour

    d = detour.drive_edges()
    lines = [to_metric(line) for (rid, _d), line in load_network().path_lines.items()
             if rid.startswith(("R_AB", "R_TB"))]
    if not lines or not seg_idx:
        return set()
    tree = shapely.STRtree(lines)
    pts, owner = [], []
    for i in seg_idx:
        e = LineString(d.xy[i])
        k = max(2, int(e.length // 10) + 1)
        pts.extend(shapely.line_interpolate_point(e, np.linspace(0, 1, k), normalized=True))
        owner.extend([i] * k)
    hit_pts, _ = tree.query(np.array(pts), predicate="dwithin", distance=detour.ROUTE_NEAR_M)
    near = np.zeros(len(pts), dtype=bool)
    near[np.unique(hit_pts)] = True
    owner = np.array(owner)
    out = set()
    for i in seg_idx:
        m = owner == i
        if near[m].mean() >= 0.8:
            out.add(i)
    return out


def drive_graph(closure: dict) -> Graph:
    """The closure's 2 km drive graph without its closed segments, weighted for buses; cached."""
    from app.m4_access import detour

    key = f"{closure.get('id')}:{closure_fingerprint(closure['id']) if closure.get('id') else ''}"
    if key in _GRAPHS:
        return _GRAPHS[key]
    sub = detour.build_subgraph(closure)
    d = detour.drive_edges()
    bus = _bus_segments(sub.seg_idx)
    g = nx.DiGraph()
    node_xy: dict[int, tuple[float, float]] = {}
    for i in sub.seg_idx:
        u, v = int(d.u[i]), int(d.v[i])
        node_xy.setdefault(u, tuple(d.xy[i][0]))
        node_xy.setdefault(v, tuple(d.xy[i][-1]))
        if i in sub.closed:
            continue
        w = float(d.length[i]) * (1.0 if i in bus else BUS_FACTOR)
        if d.oneway[i] >= 0:
            g.add_edge(u, v, w=w, seg=i)
        if d.oneway[i] <= 0:
            g.add_edge(v, u, w=w, seg=i)
    nodes = np.array(sorted(n for n in g.nodes), dtype=np.int64)
    xy = np.array([node_xy[int(n)] for n in nodes]) if len(nodes) else np.zeros((0, 2))
    out = Graph(g, node_xy, nodes, xy)
    if len(_GRAPHS) > 8:
        _GRAPHS.clear()
    _GRAPHS[key] = out
    return out


def _near_nodes(gr: Graph, x: float, y: float) -> list[int]:
    if not len(gr.nodes):
        return []
    dist = np.hypot(gr.xy[:, 0] - x, gr.xy[:, 1] - y)
    order = np.argsort(dist, kind="stable")[:SNAP_K]
    return [int(gr.nodes[i]) for i in order if dist[i] <= SNAP_M]


def route_detour(gr: Graph, a_xy: tuple[float, float], b_xy: tuple[float, float]) -> tuple[LineString, list[int]] | None:
    """(metric line, drive segment ids) of the cheapest path from near A to near B, or None."""
    from app.m4_access import detour

    d = detour.drive_edges()
    for s in _near_nodes(gr, *a_xy):
        for t in _near_nodes(gr, *b_xy):
            if s == t:
                continue
            try:
                nodes = nx.shortest_path(gr.g, s, t, weight="w")
            except nx.NetworkXNoPath:
                continue
            coords: list = [a_xy]
            segs = []
            for u, v in zip(nodes, nodes[1:]):
                i = gr.g.edges[u, v]["seg"]
                segs.append(i)
                c = d.xy[i] if int(d.u[i]) == u else d.xy[i][::-1]
                coords.extend(map(tuple, c))
            coords.append(b_xy)
            return LineString(coords), segs
    return None


# --- minutes per weekday and hour -------------------------------------------------------------------

def _path_time(m: dc.StreetMatch, day: int, hour: int, w: np.ndarray | None) -> tuple[float, float, int]:
    """(seconds over the path, measured share of its length, distinct trips used) at weekday/hour."""
    total = float(m.slice_len_arr.sum())
    if total <= 0:
        return float("nan"), 0.0, 0
    paces: dict[int | None, float] = {}
    blocks: set[int] = set()
    for u in set(m.slice_unit):
        if u is None or u not in m.units:
            paces[u] = float("nan")
            continue
        vals, blk = m.units[u].sorted_day(day, hour)
        ww = np.ones(len(vals), dtype=int) if w is None else w[blk]
        paces[u] = dc._wmedian_sorted(vals, ww)
        if not np.isnan(paces[u]):
            blocks.update(int(b) for b in blk)
    p = np.array([paces[u] for u in m.slice_unit])
    ok = ~np.isnan(p)
    covered = float(m.slice_len_arr[ok].sum())
    share = covered / total
    if share < MIN_COVERAGE or covered <= 0:
        return float("nan"), share, len(blocks)
    t = float((m.slice_len_arr[ok] * p[ok]).sum())
    return t * total / covered, share, len(blocks)


@dataclass
class LineModel:
    cut: Cut
    mode: str
    short: str
    a_name: str
    b_name: str
    normal_m: float | None
    detour: LineString | None
    detour_match: dc.StreetMatch | None
    normal_match: dc.StreetMatch | None
    own: pd.DataFrame          # the line's measured runs A -> B: run, day, hour, block
    coverage: float | None

    def __post_init__(self) -> None:
        o = self.own
        self._own = dc.StreetObs(pace=o["run"].to_numpy(float), hour=o["hour"].to_numpy(int),
                                 block=o["block"].to_numpy(int), day=o["day"].to_numpy(int))
        self._memo: dict[tuple[int, int], tuple] = {}

    def cell(self, day: int, hour: int, w: np.ndarray | None = None) -> tuple[float, float, float, float, int]:
        """(normal s, detour s, extra s, coverage, n) at a weekday and hour; NaN when not measured."""
        if w is None and (day, hour) in self._memo:
            return self._memo[(day, hour)]
        if self.detour_match is None:
            return (float("nan"),) * 4 + (0,)
        det, cov, n = _path_time(self.detour_match, day, hour, w)
        vals, blk = self._own.sorted_day(day, hour)
        normal = dc._wmedian_sorted(vals, np.ones(len(vals), dtype=int) if w is None else w[blk])
        if np.isnan(normal) and self.normal_match is not None:
            normal, _c, _n = _path_time(self.normal_match, day, hour, w)
        out = (normal, det, det - normal, cov, n)
        if w is None:
            self._memo[(day, hour)] = out
        return out


def _own_runs(ev: pd.DataFrame, c: Cut, blocks: dict[tuple[str, str], int]) -> pd.DataFrame:
    x = ev[(ev["route_id"] == c.route_id) & (ev["direction_id"] == c.direction_id)]
    gap = c.order.index(c.b) - c.order.index(c.a)
    a = x[x["stop_id"] == c.a][["trip_id", "service_date", "stop_index", "dep"]]
    b = x[x["stop_id"] == c.b][["trip_id", "service_date", "stop_index", "arr"]]
    j = a.merge(b, on=["trip_id", "service_date"], suffixes=("_a", "_b"))
    j = j[(j["stop_index_b"] - j["stop_index_a"] == gap)].dropna(subset=["dep", "arr"])
    j = j.assign(run=j["arr"] - j["dep"])
    j = j[j["run"] > 0].drop_duplicates(["trip_id", "service_date"])
    local = [from_unix(t) for t in j["dep"]]
    return pd.DataFrame({"run": j["run"].to_numpy(float), "day": [t.weekday() for t in local],
                         "hour": [t.hour for t in local],
                         "block": [blocks.setdefault((t, s), len(blocks)) for t, s in zip(j["trip_id"], j["service_date"])]})


def _normal_path(c: Cut, day: date) -> list[LineString] | None:
    """The in-force GTFS shape from A to B of a trip of the line that runs A ... B (as recorded)."""
    tt_ = timetable_day(day)
    want = tuple(c.order[c.order.index(c.a):c.order.index(c.b) + 1])
    for plan in tt_.trips.values():
        if plan.route_id != c.route_id or plan.direction_id != c.direction_id:
            continue
        ids = plan.stop_ids
        for k in range(len(ids) - len(want) + 1):
            if ids[k:k + len(want)] == want:
                return list(dc.tt.pattern_geometry(plan).segments[k:k + len(want) - 1])
    return None


def line_models(closure: dict, cuts: list[Cut], ev: pd.DataFrame, seg: pd.DataFrame, day: date,
                blocks: dict[tuple[str, str], int]) -> list[LineModel]:
    own_routes = set(dc.closure_routes(closure)) | {c.route_id for c in cuts}
    tt_ = timetable_day(day)
    gr = drive_graph(closure)
    short = dc._short_names(tt_.sha)
    out = []
    from app.m4_access import detour

    area = to_metric(from_geojson(closure["geometry"])).buffer(detour.RADIUS_M + dc.AREA_M) \
        if closure.get("geometry") else None
    index = dc.seg_index(seg, area, blocks) if area is not None else None
    excl = frozenset(own_routes)
    for c in cuts:
        a_xy, b_xy = tt_.stop_xy.get(c.a), tt_.stop_xy.get(c.b)
        mode = next((m for p, m in MODES.items() if c.route_id.startswith(p)), "autobuz")
        normal = _normal_path(c, day)
        normal_m = round(sum(p.length for p in normal), 0) if normal else None
        found = route_detour(gr, a_xy, b_xy) if a_xy and b_xy else None
        det_line = found[0] if found else None
        det_match = (dc.match_streets([det_line], seg, blocks, index=index, exclude=excl)
                     if det_line is not None and det_line.length > 0 else None)
        norm_match = dc.match_streets(normal, seg, blocks, index=index) if normal else None
        cov = None
        if det_match is not None:
            ok = [u is not None and u in det_match.units and len(det_match.units[u].pace) >= dc.MIN_OBS
                  for u in det_match.slice_unit]
            tot = float(det_match.slice_len_arr.sum())
            cov = round(float(det_match.slice_len_arr[np.array(ok, dtype=bool)].sum()) / tot, 3) if tot else None
        out.append(LineModel(c, mode, str(short.get(c.route_id) or c.route_id.split("_")[-1]),
                             tt_.stop_names.get(c.a, c.a), tt_.stop_names.get(c.b, c.b), normal_m, det_line,
                             det_match, norm_match, _own_runs(ev, c, blocks), cov))
    return out


def _streets(m: LineModel) -> list[DetourStreet]:
    from app.m4_access import detour

    if m.detour_match is None:
        return []
    d = detour.drive_edges()
    out: list[DetourStreet] = []
    for length, u in zip(m.detour_match.slice_len, m.detour_match.slice_unit):
        name = d.names[u] if u is not None else None
        measured = u is not None and u in m.detour_match.units and len(m.detour_match.units[u].pace) >= dc.MIN_OBS
        if out and out[-1].name == name and out[-1].measured == measured:
            out[-1] = out[-1].model_copy(update={"meters": out[-1].meters + length})
        else:
            out.append(DetourStreet(name=name, meters=length, measured=measured))
    return [s.model_copy(update={"meters": round(s.meters)}) for s in out]


# --- windows ------------------------------------------------------------------------------------------

def recorded_cells(seg: pd.DataFrame) -> list[tuple[int, int]]:
    """(weekday, hour) with recorded runs."""
    if not len(seg):
        return []
    days = seg["day_type"].map({d: i for i, d in enumerate(DAYS)})
    return sorted(set(zip(days.astype(int), seg["hour_local"].astype(int))))


def _minute_cells(start, n: int) -> np.ndarray:
    idx = pd.date_range(start, periods=n, freq="min", tz=TZ)
    return np.asarray(idx.weekday) * 24 + np.asarray(idx.hour)


def compute(closure: dict, analysis: dict, hours: float | None = None, start: str | None = None,
            end: str | None = None) -> MeasuredWindows:
    rng_np = np.random.default_rng(SEED)
    ttb = imp.timetable_for_closure(closure)
    keys = win.lost_keys(analysis["stops"])
    rng = win.search_range(closure, ttb, hours, start, end)
    costs = win.minute_costs(ttb, keys, rng.start, rng.end)
    _common, cw = win.split_common(win.conflict_windows(closure, rng), rng)
    cands = win.candidates(costs, rng, cw)
    cov = store.coverage()
    label = I18n(ro=f"după traficul măsurat, {cov['labelRo']}", en=f"by measured traffic, {cov['labelEn']}") if cov else None
    base = dict(closureId=closure["id"], hours=rng.hours, searchFrom=iso(rng.start),
                searchTo=iso(rng.end - timedelta(hours=rng.hours)), method=METHOD)
    provs = [ttb.provenance]
    if cov is None:
        return MeasuredWindows(status="fara_inregistrare", label=None, lines=[], candidates=[], note=NOTES["fara_inregistrare"],
                               unmeasuredCandidates=len(cands), provenance=provs, **base)
    ev, seg = store.events(), store.segments()
    day = max(date.fromisoformat(x) for x in ev["service_date"].unique())
    cuts, _terminal = cuts_for(closure, analysis, ttb, day)
    if not cuts:
        return MeasuredWindows(status="fara_ocolire", label=label, lines=[], candidates=[], note=NOTES["fara_ocolire"],
                               unmeasuredCandidates=len(cands), provenance=provs, **base)
    blocks: dict[tuple[str, str], int] = {}
    models = line_models(closure, cuts, ev, seg, day, blocks)
    cells = recorded_cells(seg)
    w_boot = rng_np.poisson(1.0, size=(BOOT, max(1, len(blocks))))
    usable = [m for m in models if m.detour_match is not None and (m.coverage or 0) >= MIN_COVERAGE]
    lines_out, extra_tab = [], {}
    for m in models:
        rows, tab = [], {}
        for dd, h in cells:
            normal, det, extra, c_, n = m.cell(dd, h)
            tab[dd * 24 + h] = extra
            if np.isnan(det) and np.isnan(normal):
                continue
            r = lambda v: None if np.isnan(v) else round(float(v), 1)  # noqa: E731
            rows.append(DetourHourCost(dayType=DAYS[dd], hour=h, normalSec=r(normal), detourSec=r(det),
                                       extraSec=r(extra), coverage=round(c_, 3), n=n))
        extra_tab[id(m)] = tab
        if m.detour_match is None:
            status, note = "fara_drum", I18n(ro="Nu am găsit un drum pe străzi între cele două stații.",
                                            en="No street path found between the two stops.")
        elif m in usable:
            status, note = "ok", None
        else:
            status = "neconcludent"
            note = I18n(ro=f"Doar {m.coverage or 0:.0%} din ocolire are autobuze măsurate.".replace("%", " %"),
                        en=f"Only {m.coverage or 0:.0%} of the detour has measured buses.")
        if m.mode == "tramvai":
            tram = I18n(ro="Tramvaiul nu poate ocoli pe stradă: minutele sunt pentru un autobuz pe acest traseu.",
                        en="A tram cannot detour on streets: the minutes are for a bus on this path.")
            note = tram if note is None else I18n(ro=f"{note.ro} {tram.ro}", en=f"{note.en} {tram.en}")
        lines_out.append(DetourLine(
            routeId=m.cut.route_id, shortName=m.short, directionId=m.cut.direction_id, mode=m.mode,
            fromStopId=m.cut.a, fromStopName=m.a_name, toStopId=m.cut.b, toStopName=m.b_name, cutStopIds=m.cut.cut,
            normalMeters=m.normal_m, detourMeters=round(m.detour.length) if m.detour is not None else None,
            detourPath=to_geojson(to_wgs84(m.detour)) if m.detour is not None else None, coverage=m.coverage,
            streets=_streets(m), byHour=rows, status=status, note=note))
    if not usable:
        return MeasuredWindows(status="neconcludent", label=label, lines=lines_out, candidates=[],
                               note=NOTES["neconcludent"],
                               unmeasuredCandidates=len(cands), provenance=provs, **base)
    # per minute of the search range: trips at A, of them at a measured weekday/hour, and their minutes
    n = len(costs)
    cell_of = _minute_cells(rng.start, n)
    deps = [win.minute_costs(ttb, [(m.cut.a, m.cut.route_id, m.cut.direction_id)], rng.start, rng.end)
            for m in usable]
    trips, known, vm = np.zeros(n), np.zeros(n), np.zeros(n)
    for m, dp in zip(usable, deps):
        ex = np.array([extra_tab[id(m)].get(int(c), np.nan) for c in cell_of])
        ok = ~np.isnan(ex) & (dp > 0)
        trips += dp
        known += np.where(ok, dp, 0.0)
        vm += np.where(ok, dp * np.nan_to_num(ex) / 60.0, 0.0)
    cs = {k: np.concatenate([[0.0], np.cumsum(v)]) for k, v in (("vm", vm), ("known", known), ("trips", trips))}
    h = int(round(rng.hours * 60))
    scored, unmeasured = [], 0
    for c in cands:
        i = int(round((c.start - rng.start).total_seconds() / 60))
        t_all = cs["trips"][i + h] - cs["trips"][i]
        t_known = cs["known"][i + h] - cs["known"][i]
        share = 1.0 if t_all <= 0 else t_known / t_all
        if share < MIN_TRIP_SHARE:
            unmeasured += 1
            continue
        minutes = 0.0 if t_known <= 0 else (cs["vm"][i + h] - cs["vm"][i]) * t_all / t_known
        scored.append((minutes, c, t_all, i, share))
    scored.sort(key=lambda x: (round(x[0], 3), x[1].departures, x[1].start))
    chosen = []
    for s_ in scored:
        if len(chosen) >= win.TOP_N:
            break
        if not any(s_[1].overlaps(o[1]) for o in chosen):
            chosen.append(s_)
    # bootstrap the chosen windows' minutes: one trip (own line or other line) = one block
    boot = np.full((BOOT, len(chosen)), np.nan)
    weak = np.zeros(len(chosen), dtype=bool)
    buckets = []
    for _vmin, _c, _t, i, _sh in chosen:
        per = []
        for m, dp in zip(usable, deps):
            cc, dd = cell_of[i:i + h], dp[i:i + h]
            tab = extra_tab[id(m)]
            per.append({int(k): float(dd[cc == k].sum()) for k in np.unique(cc[dd > 0])
                        if not np.isnan(tab.get(int(k), np.nan))})
        buckets.append(per)
    for j, per in enumerate(buckets):
        weak[j] = chosen[j][4] < 1.0 or any(usable[li].cell(k // 24, k % 24)[4] < dc.MIN_TRIPS
                                            for li in range(len(usable)) for k in per[li])
    keys_by_line = [{k for per in buckets for k in per[li]} for li in range(len(usable))]
    for b in range(BOOT):
        tabs = [{k: m.cell(k // 24, k % 24, w_boot[b])[2] for k in keys_by_line[li]} for li, m in enumerate(usable)]
        for j, per in enumerate(buckets):
            num = den = 0.0
            for li in range(len(usable)):
                for k, cnt in per[li].items():
                    v = tabs[li][k]
                    if not np.isnan(v):
                        num += cnt * v / 60.0
                        den += cnt
            if den > 0:
                boot[b, j] = num * chosen[j][2] / den
    out_c = []
    for j, (vmin, c, ntrips, _i, share) in enumerate(chosen):
        bj = boot[:, j][~np.isnan(boot[:, j])]
        lo, hi = (np.percentile(bj, [5, 95]) if len(bj) else (None, None))
        out_c.append(MeasuredWindow(
            window={"start": iso(c.start), "end": iso(c.end)}, rank=j + 1, departuresLost=c.departures,
            trips=int(round(ntrips)), measuredTripShare=round(float(share), 3), detourMinutes=round(float(vmin), 1),
            detourMinutesLow=None if lo is None else round(float(lo), 1),
            detourMinutesHigh=None if hi is None else round(float(hi), 1),
            conclusive=not weak[j], conflicts=c.conflicts))
    provs += [prov.vehicles_provenance(cov["last"], f"{cov['labelRo']}; orarul observat (L0)"),
              imp.osm_provenance("ocolirea pe străzile OSM și străzile pe care merg alte linii / detour streets")]
    return MeasuredWindows(status="ok", label=label, lines=lines_out, candidates=out_c,
                           note=None if out_c else NOTES["fara_ore"],
                           unmeasuredCandidates=unmeasured, provenance=provs, **base)


def job_key(closure_id: str, hours: float | None = None, start: str | None = None, end: str | None = None) -> str:
    from app.config import now

    stems = store.built_stems()
    return (f"windows-measured:v{ALGO_VERSION}:{closure_id}:{closure_fingerprint(closure_id)}:"
            f"{win.others_fingerprint()}:{hours}:{start or iso(now())}:{end}:{len(stems)}:{(stems or [''])[-1]}")


def suggest(closure_id: str, hours: float | None = None, start: str | None = None,
            end: str | None = None) -> MeasuredWindows:
    closure, analysis = win.load_closure(closure_id)
    return compute(closure, analysis, hours=hours, start=start, end=end)
