"""M5 bike impact of a closure (SPEC §6.5, CONTRACT BikeImpact).

- `lanesAffected`: bike infrastructure (cycleway, track, designated path, painted lane; see
  app.m5_bike.lts) inside the closure buffer, clipped to the buffer.
- `parkingAffected`: OSM bike parking inside the buffer.
- `detourStress`: the LTS-weighted shortest bike route between the two ends of the closure with
  the closure removed (segments at least half inside the buffer). Cost = length × factor
  (LTS 1: 1.0, 2: 1.3, 3: 2.0, 4: 4.0, unknown: 2.5), one-way streets respected unless
  `oneway:bicycle=no`. The route is cut into runs of the same street name and LTS.
- Missing OSM data is „necunoscut”: an empty `lanesAffected` means none is mapped in OSM, and
  the provenance note says so; it never means „nu există pistă”.

    bike_impact_for(closure: dict, extra_lanes=None) -> BikeImpact   (extra lanes routed as LTS 1)
    bike_impact(closure_id) -> BikeImpact
    bike_impact_with_lane(closure_id, lane_geometry) -> BikeImpact   (mitigation `bike_lane`)
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any

import networkx as nx
import numpy as np
import shapely
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge

from app.common import state
from app.common.errors import invalid, not_found
from app.common.geo import from_geojson, to_geojson, to_metric, to_wgs84
from app.m1_disruption.impact import osm_provenance
from app.m5_bike.osm_bike import BikeData, bike_data
from app.models.v2 import BikeDetour, BikeImpact, BikeLane, BikeParking

LTS_FACTOR: dict[int | None, float] = {1: 1.0, 2: 1.3, 3: 2.0, 4: 4.0, None: 2.5}
AREA_MIN_M = 1000.0
SNAP_MAX_M = 400.0
SNAP_TRIES = 5
LANE_LINK_M = 30.0
LANE_END_LINK_M = 80.0
LANE_LINKS = 4
LANE_STEP_M = 25.0
MIN_PART_M = 1.0


@dataclass
class _Closure:
    geom: Any            # metric closure geometry
    buf: Any             # metric buffer


def _closure(closure: dict) -> _Closure:
    if not closure.get("geometry"):
        raise invalid("The closure has no geometry.")
    g = to_metric(from_geojson(closure["geometry"]))
    return _Closure(g, g.buffer(float(closure.get("bufferMeters") or 30)))


def _parts(g) -> list[LineString]:
    if g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    if g.geom_type in ("MultiLineString", "GeometryCollection"):
        return [p for p in g.geoms if p.geom_type == "LineString"]
    return []


def lanes_affected(d: BikeData, c: _Closure) -> list[BikeLane]:
    hits = [int(i) for i in d.seg_tree().query(c.buf, predicate="intersects")]
    by_way: dict[int, list[int]] = {}
    for i in hits:
        w = int(d.seg_way[i])
        if d.way_bike[w]:
            by_way.setdefault(w, []).append(i)
    out: list[BikeLane] = []
    for w in sorted(by_way, key=lambda w: int(d.way_id[w])):
        merged = linemerge([LineString(d.seg_xy[i]) for i in by_way[w]])
        for part in _parts(merged.intersection(c.buf)):
            if part.length < MIN_PART_M:
                continue
            out.append(BikeLane(osmId=f"way/{int(d.way_id[w])}", name=d.way_name[w],
                                lengthMeters=round(part.length, 1), geometry=to_geojson(to_wgs84(part))))
    return out


def parking_affected(d: BikeData, c: _Closure) -> list[BikeParking]:
    out = []
    if not len(d.poi_lonlat):
        return out
    for k, (lon, lat) in enumerate(d.poi_lonlat.tolist()):
        if d.poi_kind[k] != "parking":
            continue
        if c.buf.contains(to_metric(Point(lon, lat))):
            out.append(BikeParking(osmId=d.poi_osm[k], capacity=d.poi_capacity[k],
                                   location=[round(lon, 7), round(lat, 7)]))
    return out


def _ends(geom) -> tuple[Point, Point]:
    """The two ends of the closed segment: first/last point, or the farthest pair of part ends."""
    if geom.geom_type == "LineString":
        cs = list(geom.coords)
        return Point(cs[0]), Point(cs[-1])
    ends = [Point(p.coords[i]) for p in _parts(geom) for i in (0, -1)]
    a, b = max(itertools.combinations(ends, 2), key=lambda ab: ab[0].distance(ab[1]))
    return a, b


@dataclass
class _Route:
    edges: list[dict]    # edge data along the route, in order


def _graph(d: BikeData, c: _Closure, extra_lanes: list[LineString]) -> tuple[nx.DiGraph, dict[int, tuple]]:
    a, b = _ends(c.geom)
    margin = max(AREA_MIN_M, 0.6 * a.distance(b))
    area = c.geom.envelope.buffer(margin)
    idx = [int(i) for i in d.seg_tree().query(area, predicate="intersects")]
    g = nx.DiGraph()
    node_xy: dict[int, tuple] = {}
    for i in idx:
        w = int(d.seg_way[i])
        if not d.way_ride[w]:
            continue
        line = LineString(d.seg_xy[i])
        if line.length > 0 and line.intersection(c.buf).length >= 0.5 * line.length:
            continue  # the closure: removed
        u, v = int(d.seg_u[i]), int(d.seg_v[i])
        node_xy[u] = tuple(d.seg_xy[i][0])
        node_xy[v] = tuple(d.seg_xy[i][-1])
        lts = d.way_lts[w]
        cost = float(d.seg_len[i]) * LTS_FACTOR[lts]
        attrs = {"seg": i, "lts": lts, "name": d.way_name[w], "len": float(d.seg_len[i])}
        if d.seg_oneway[i] >= 0:
            g.add_edge(u, v, cost=cost, rev=False, **attrs)
        if d.seg_oneway[i] <= 0:
            g.add_edge(v, u, cost=cost, rev=True, **attrs)
    if extra_lanes and node_xy:
        ids = np.fromiter(node_xy.keys(), dtype=np.int64)
        pts = np.array([node_xy[int(k)] for k in ids])
        new_id = -1
        for lane in extra_lanes:
            coords = list(shapely.segmentize(lane, LANE_STEP_M).coords)
            prev = None
            for j, (x, y) in enumerate(coords):
                nid, new_id = new_id, new_id - 1
                node_xy[nid] = (x, y)
                if prev is not None:
                    _lane_edge(g, prev, nid, LineString([node_xy[prev], (x, y)]))
                # join the lane to every street node nearby; its two ends reach a bit further,
                # since the closed street's own nodes at the ends are gone with the closure
                dist = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
                reach = LANE_END_LINK_M if j in (0, len(coords) - 1) else LANE_LINK_M
                for k in np.flatnonzero(dist <= reach)[np.argsort(dist[dist <= reach])][:LANE_LINKS]:
                    _lane_edge(g, nid, int(ids[k]), LineString([(x, y), tuple(pts[k])]))
                prev = nid
    return g, node_xy


def _lane_edge(g: nx.DiGraph, a: int, b: int, seg: LineString) -> None:
    attrs = {"seg": -1, "lts": 1, "name": None, "len": seg.length, "cost": seg.length * LTS_FACTOR[1]}
    g.add_edge(a, b, xy=list(seg.coords), **attrs)
    g.add_edge(b, a, xy=list(seg.coords)[::-1], **attrs)


def _candidates(g: nx.DiGraph, node_xy: dict[int, tuple], c: _Closure, end: Point, core: set[int]) -> list[int]:
    """Nodes near one end, outside the buffer, in the strongly connected core (a one-way stub
    cut off by the closure would have no way out)."""
    ids = [n for n in core if not c.buf.contains(Point(node_xy[n]))]
    if not ids:
        return []
    pts = np.array([node_xy[n] for n in ids])
    dist = np.hypot(pts[:, 0] - end.x, pts[:, 1] - end.y)
    order = np.argsort(dist)[:SNAP_TRIES]
    return [ids[k] for k in order if dist[k] <= SNAP_MAX_M]


def detour_route(d: BikeData, c: _Closure, extra_lanes: list[LineString]) -> _Route | None:
    g, node_xy = _graph(d, c, extra_lanes)
    if g.number_of_nodes() == 0:
        return None
    core = max(nx.strongly_connected_components(g), key=len)
    a, b = _ends(c.geom)
    for s, t in itertools.product(_candidates(g, node_xy, c, a, core), _candidates(g, node_xy, c, b, core)):
        try:
            path = nx.shortest_path(g, s, t, weight="cost")
        except nx.NetworkXNoPath:
            continue
        return _Route([g.edges[u, v] for u, v in zip(path, path[1:])])
    return None


def _edge_xy(d: BikeData, e: dict) -> list[tuple]:
    if e["seg"] < 0:
        return [tuple(p) for p in e["xy"]]
    xy = d.seg_xy[e["seg"]]
    return [tuple(p) for p in (xy[::-1] if e["rev"] else xy)]


def detour_stress(d: BikeData, route: _Route | None) -> list[BikeDetour]:
    if route is None:
        return []
    out: list[BikeDetour] = []
    for (name, lts), run in itertools.groupby(route.edges, key=lambda e: (e["name"], e["lts"])):
        run = list(run)
        coords: list[tuple] = []
        for e in run:
            xy = _edge_xy(d, e)
            coords.extend(xy if not coords else xy[1:])
        if len(coords) < 2:
            continue
        line = LineString(coords)
        out.append(BikeDetour(name=name, lts=lts, lengthMeters=round(sum(e["len"] for e in run), 1),
                              geometry=to_geojson(to_wgs84(line))))
    return out


def _lane_lines(extra_lanes: list[Any] | None) -> list[LineString]:
    out = []
    for lane in extra_lanes or []:
        g = from_geojson(lane)
        if isinstance(g, MultiLineString):
            out.extend(to_metric(p) for p in g.geoms)
        elif isinstance(g, LineString):
            out.append(to_metric(g))
        else:
            raise invalid("A bike lane must be a GeoJSON LineString.")
    return out


def bike_impact_for(closure: dict, extra_lanes: list[Any] | None = None) -> BikeImpact:
    """BikeImpact of a closure dict (stored or not). `extra_lanes`: temporary lanes, LTS 1."""
    d = bike_data()
    c = _closure(closure)
    lanes = lanes_affected(d, c)
    parking = parking_affected(d, c)
    route = detour_route(d, c, _lane_lines(extra_lanes))
    stress = detour_stress(d, route)
    notes = ["nivel de stres LTS din etichetele OSM (tabelul din README) / LTS from OSM tags",
             "ocolire = cel mai scurt traseu ponderat cu LTS între capetele lucrării / LTS-weighted shortest route"]
    if not lanes:
        notes.append("nicio pistă cartografiată în OSM în zona lucrării: necunoscut, nu «nu există pistă» / "
                     "no bike way mapped in OSM here: unknown, not 'no bike lane'")
    if route is None:
        notes.append("traseu de ocolire necunoscut: graful OSM nu leagă capetele / detour unknown")
    if extra_lanes:
        notes.append(f"{len(extra_lanes)} pistă temporară propusă, tratată ca LTS 1 / proposed temporary lane as LTS 1")
    return BikeImpact(closureId=closure.get("id") or "", lanesAffected=lanes, parkingAffected=parking,
                      detourStress=stress, provenance=[osm_provenance("; ".join(notes))])


def _stored(closure_id: str) -> dict:
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id}.")
    return closure


def bike_impact(closure_id: str) -> BikeImpact:
    return bike_impact_for(_stored(closure_id))


def bike_impact_with_lane(closure_id: str, lane_geometry: Any) -> BikeImpact:
    """The `bike_lane` mitigation: the same closure with a temporary lane (GeoJSON LineString)."""
    return bike_impact_for(_stored(closure_id), [lane_geometry])
