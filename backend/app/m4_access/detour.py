"""Detour load (Braess F1, SPEC §6.4): which streets take the traffic when a segment closes.

Method (structure of the street network, not traffic volumes):
- the OSM drive graph (pyrosm `driving`, oneway respected) within 2 km of the closure;
- edge betweenness centrality with k = 200 sampled nodes (fixed seed, so numbers are stable),
  weight = length in metres;
- "after" = the same graph without the edges inside the closure buffer (both ends and the
  middle of the edge within the buffer, so cross streets that only touch it stay open);
- per segment, both directions summed; the open segments that gain are joined into street
  pieces (same name, touching), each with the length-weighted mean before and after;
- the top 5 pieces by absolute change (after − before, not percent, so a quiet lane with a
  tiny base does not win); only pieces that gain are "edges that take the detour" (CONTRACT),
  the closed segments and the streets that lose through traffic are left out;
- `routeIdsOnEdge` = lines whose path runs within 15 m of the way for at least 50 m
  (80 % of the way when the way is shorter than 62.5 m);
- `routesSlowedRisk` = those lines minus the closure's own lines.

Wording on screen: „risc de încetinire”, never „vor fi încetinite”.

    compute_detour_load(closure) -> DetourLoad    slow (graph + 2 × betweenness), no cache
    job_key(closure_id) / compute_for(closure_id) / cached_for(closure_id)
                                                  the same through app.common.jobs' cache
"""

from __future__ import annotations

import hashlib
import logging
import pickle
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import networkx as nx
import numpy as np
from shapely import STRtree
from shapely.geometry import LineString, Point
from shapely.ops import linemerge

from app.common import jobs, state
from app.common.errors import not_found
from app.common.city import load_network
from app.common.geo import from_geojson, project_lonlats, to_geojson, to_metric
from app.config import get_settings
from app.m1_disruption.impact import counts_as_lost, osm_provenance
from app.models.base import I18n
from app.models.v2 import DetourEdge, DetourLoad

log = logging.getLogger(__name__)

ALGO_VERSION = 2
OSM_FILE = "osm/timisoara.osm.pbf"
RADIUS_M = 2000.0
K_SAMPLES = 200
SEED = 20261113
TOP_N = 5
ROUTE_NEAR_M = 15.0
ROUTE_MIN_M = 50.0

LABEL = I18n(
    ro="Structura rețelei de străzi, nu volume de trafic. Liniile de pe aceste străzi au risc de încetinire.",
    en="Street network structure, not traffic volumes. Lines on these streets have a risk of slowing down.",
)
METHOD_NOTE = (f"centralitate de intermediere pe muchii, k={K_SAMPLES} noduri eșantionate (seed fix), "
               f"graf auto OSM pe {RADIUS_M / 1000:.0f} km în jurul lucrării / edge betweenness, "
               f"k={K_SAMPLES} sampled nodes, OSM drive graph within {RADIUS_M / 1000:.0f} km")


# --- the city drive graph, cached ------------------------------------------------------


@dataclass
class DriveEdges:
    u: np.ndarray            # OSM node id per segment
    v: np.ndarray
    length: np.ndarray       # metres
    way: np.ndarray          # OSM way id per segment
    oneway: np.ndarray       # 0 both ways, 1 u->v only, -1 v->u only
    names: list[str | None]  # per segment
    coords: list[np.ndarray] # WGS84 [lon, lat] per segment
    xy: list[np.ndarray]     # UTM 34N per segment


def _pbf() -> Path:
    return get_settings().data_dir / OSM_FILE


def _oneway(raw, junction) -> int:
    v = str(raw).strip().lower() if isinstance(raw, str) else ""
    if v in ("yes", "true", "1"):
        return 1
    if v == "-1":
        return -1
    if v in ("no", "false", "0"):
        return 0
    return 1 if isinstance(junction, str) and junction in ("roundabout", "circular") else 0


def _build_drive(pbf: Path) -> DriveEdges:
    from pyrosm import OSM  # slow import, only when building

    _nodes, edges = OSM(str(pbf)).get_network(network_type="driving", nodes=True)
    coords = [np.asarray(g.coords, dtype=float)[:, :2] for g in edges.geometry]
    xy = [project_lonlats(map(tuple, c)) for c in coords]
    return DriveEdges(
        u=edges["u"].to_numpy(dtype=np.int64),
        v=edges["v"].to_numpy(dtype=np.int64),
        length=edges["length"].to_numpy(dtype=float),
        way=edges["id"].to_numpy(dtype=np.int64),
        oneway=np.array([_oneway(o, j) for o, j in zip(edges["oneway"], edges["junction"])], dtype=np.int8),
        names=[n if isinstance(n, str) and n.strip() else None for n in edges["name"]],
        coords=coords,
        xy=xy,
    )


_lock = threading.Lock()


@lru_cache(maxsize=1)
def drive_edges() -> DriveEdges:
    """Every OSM drive segment of the extract, cached as a pickle in $DATA_DIR/cache."""
    pbf = _pbf()
    if not pbf.is_file():
        raise FileNotFoundError(f"OSM extract missing: {pbf} (run `make data`)")
    st = pbf.stat()
    key = hashlib.sha1(f"{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()[:12]
    cache = get_settings().cache_dir / f"drive_edges_v1_{key}.pkl"
    with _lock:
        if cache.is_file():
            try:
                return pickle.loads(cache.read_bytes())
            except Exception:
                log.warning("drive edge cache unreadable, rebuilding")
        data = _build_drive(pbf)
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_bytes(pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL))
        tmp.replace(cache)
        return data


@lru_cache(maxsize=1)
def _drive_tree() -> STRtree:
    d = drive_edges()
    return STRtree([LineString(x) for x in d.xy])


@lru_cache(maxsize=1)
def _route_lines_metric() -> dict[tuple[str, int], LineString]:
    return {k: to_metric(line) for k, line in load_network().path_lines.items()}


# --- the computation -----------------------------------------------------------------


def closure_geometry_metric(closure: dict):
    return to_metric(from_geojson(closure["geometry"]))


def own_routes(closure: dict) -> set[str]:
    """Lines the closure itself suspends or diverts (they are not a 'risk', they are closed)."""
    ids = set(closure.get("routeIds") or [])
    ids |= {a["routeId"] for a in closure.get("routeActions") or []}
    try:
        analysis = state.read("closures", closure["id"], state.PART_ANALYSIS) if closure.get("id") else None
    except ValueError:
        analysis = None
    ids |= {r["routeId"] for r in (analysis or {}).get("stops") or [] if counts_as_lost(r)}
    return ids


def job_key(closure_id: str) -> str:
    """Key of a stored closure's detour load in the job cache (app.common.jobs)."""
    return f"detour-load:v{ALGO_VERSION}:{closure_id}:{jobs.closure_fingerprint(closure_id)}"


def cached_for(closure_id: str) -> DetourLoad | None:
    """The cached detour load of a stored closure (never computes), or None."""
    try:
        hit = jobs.cached(job_key(closure_id))
    except Exception:
        return None
    return hit if isinstance(hit, DetourLoad) else None


def compute_for(closure_id: str) -> DetourLoad:
    """Detour load of a stored closure, through the job cache (synchronous; for warm-up)."""
    closure = state.read("closures", closure_id)
    if closure is None:
        raise not_found(f"No closure {closure_id}.")
    return jobs.compute_and_cache(job_key(closure_id), lambda: compute_detour_load(closure))


@dataclass
class Subgraph:
    graph: nx.DiGraph
    seg_idx: list[int]                     # segment indices of the drive edges inside the radius
    closed: set[int]                       # segment indices inside the closure buffer


def build_subgraph(closure: dict) -> Subgraph:
    d = drive_edges()
    geom = closure_geometry_metric(closure)
    area = geom.buffer(RADIUS_M)
    buf = geom.buffer(float(closure.get("bufferMeters") or 30))
    idx = sorted(int(i) for i in _drive_tree().query(area, predicate="intersects"))
    closed: set[int] = set()
    g = nx.DiGraph()
    # nodes in a fixed order, so the sampled nodes are the same before and after
    nodes = sorted({int(d.u[i]) for i in idx} | {int(d.v[i]) for i in idx})
    g.add_nodes_from(nodes)
    for i in idx:
        xy = d.xy[i]
        mid = LineString(xy).interpolate(0.5, normalized=True)
        if buf.contains(Point(xy[0])) and buf.contains(Point(xy[-1])) and buf.contains(mid):
            closed.add(i)
        u, v, w = int(d.u[i]), int(d.v[i]), float(d.length[i])
        if d.oneway[i] >= 0:
            g.add_edge(u, v, length=w, seg=i)
        if d.oneway[i] <= 0:
            g.add_edge(v, u, length=w, seg=i)
    return Subgraph(g, idx, closed)


def _betweenness(g: nx.DiGraph) -> dict[int, float]:
    """Per segment: edge betweenness of both directions summed."""
    k = min(K_SAMPLES, g.number_of_nodes())
    eb = nx.edge_betweenness_centrality(g, k=k, normalized=True, weight="length", seed=SEED)
    out: dict[int, float] = {}
    for (u, v), val in eb.items():
        seg = g.edges[u, v]["seg"]
        out[seg] = out.get(seg, 0.0) + float(val)
    return out


def _pieces(sub: Subgraph, before: dict[int, float], after: dict[int, float]) -> list[tuple]:
    """Open segments that gain centrality, joined into street pieces (same name, touching).

    Returns [(absolute increase, segments, before, after)] sorted by the increase, largest
    first; before/after are length-weighted means over the piece. Ways with no through
    path before (centrality 0) are left out: a relative change has no meaning there.
    """
    d = drive_edges()
    gain = [i for i in sub.seg_idx if i not in sub.closed and after.get(i, 0.0) > before.get(i, 0.0)]
    parent = {i: i for i in gain}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen: dict[tuple, int] = {}
    for i in gain:
        key = d.names[i] or f"way:{int(d.way[i])}"
        for node in (int(d.u[i]), int(d.v[i])):
            j = seen.setdefault((key, node), i)
            if j != i:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in gain:
        groups.setdefault(find(i), []).append(i)
    rows = []
    for segs in groups.values():
        segs.sort()
        total = float(sum(d.length[i] for i in segs))
        if total <= 0:
            continue
        b = float(sum(before.get(i, 0.0) * d.length[i] for i in segs) / total)
        a = float(sum(after.get(i, 0.0) * d.length[i] for i in segs) / total)
        if b <= 0:
            continue
        rows.append((a - b, segs, b, a))
    rows.sort(key=lambda r: (-r[0], r[1][0]))
    return rows


def _piece_line(segs: list[int]) -> LineString:
    d = drive_edges()
    merged = linemerge([LineString(d.coords[i]) for i in segs])
    if merged.geom_type == "MultiLineString":
        merged = max(merged.geoms, key=lambda p: to_metric(p).length)
    return merged


def routes_on(line_metric: LineString) -> list[str]:
    """Lines whose path runs within 15 m of the way for at least 50 m (80 % of a short way)."""
    need = min(ROUTE_MIN_M, 0.8 * line_metric.length)
    zone = line_metric.buffer(ROUTE_NEAR_M)
    out = set()
    for (route_id, _dir), path in _route_lines_metric().items():
        if not path.intersects(zone):
            continue
        if path.intersection(zone).length >= need:
            out.add(route_id)
    return sorted(out)


def compute_detour_load(closure: dict) -> DetourLoad:
    """DetourLoad (spillover left null: app.m4_access.spillover adds it) for a closure dict.

    Takes 10-30 s on a 2 km graph; callers go through the job cache (job_key / respond).
    Works on an unsaved closure dict too (the decide module's `segment` scenarios).
    """
    sub = build_subgraph(closure)
    before = _betweenness(sub.graph)
    after_g = sub.graph.copy()
    after_g.remove_edges_from([(u, v) for u, v, s in sub.graph.edges(data="seg") if s in sub.closed])
    after = _betweenness(after_g)

    rows = _pieces(sub, before, after)
    own = own_routes(closure)
    edges: list[DetourEdge] = []
    risk: set[str] = set()
    d = drive_edges()
    for _chg, segs, b, a in rows[:TOP_N]:
        line = _piece_line(segs)
        on = routes_on(to_metric(line))
        risk |= set(on) - own
        name = next((d.names[i] for i in segs if d.names[i]), None)
        edges.append(DetourEdge(name=name, geometry=to_geojson(line), centralityBefore=round(b, 6),
                                centralityAfter=round(a, 6), changePct=round((a - b) / b * 100.0, 1),
                                routeIdsOnEdge=on))
    note = (f"{METHOD_NOTE}; {sub.graph.number_of_nodes()} noduri, {len(sub.seg_idx)} segmente, "
            f"{len(sub.closed)} închise / nodes, segments, closed")
    result = DetourLoad(
        closureId=closure.get("id") or "",
        edges=edges,
        routesSlowedRisk=sorted(risk),
        label=LABEL,
        spillover=None,
        provenance=[osm_provenance(note), load_network().provenance],
    )
    return result


def edge_lines(result: DetourLoad) -> list[LineString]:
    """WGS84 lines of the top edges (for shared_detour and spillover)."""
    return [LineString(e.geometry.coordinates) for e in result.edges]
