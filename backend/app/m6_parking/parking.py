"""M6 parking around a closure (SPEC §6.6).

- streetsAffected / lotsAffected: Timpark features (`/api/mobile/parking`)
  that intersect the closure buffer, with the city's ids, names and tariff
  colours unchanged.
- Park & Ride: the first or last stop of a direction (GTFS stop order of the
  most common trip pattern), more than 3 km from Piața Victoriei and within
  500 m of a Timpark lot. walkMeters = straight line from the stop to the lot
  (0 when the stop stands inside the lot). There is no occupancy data.

Public:
    closure_buffer(closure) -> WGS84 geometry
    all_park_and_ride() -> list[ParkAndRide]                every option in the city
    park_and_ride_options(closure_id) -> list[ParkAndRide]  the options for one closure
    parking_impact(closure_id) -> ParkingImpact
"""

from __future__ import annotations

from functools import lru_cache

from shapely import STRtree
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from app.common import gtfs, state
from app.common import provenance as prov
from app.common.city import load_network, load_parking
from app.common.errors import invalid, not_found
from app.common.geo import buffer_m, from_geojson, to_metric
from app.config import now
from app.m3_notices import osm_ways
from app.models.v2 import ParkAndRide, ParkingFeatureRef, ParkingImpact

CENTRE_NAME = "Piața Victoriei"     # OSM name of the square used as the city centre
MIN_CENTRE_METERS = 3000.0          # P&R: line end more than 3 km from the centre
MAX_LOT_METERS = 500.0              # P&R: a Timpark lot within 500 m
PR_LABEL = "fără date de ocupare / no occupancy data"


# --- closure geometry ------------------------------------------------------------


def load_closure(closure_id: str) -> dict:
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id}.")
    return closure


def closure_buffer(closure: dict) -> BaseGeometry:
    """The closure geometry buffered by its bufferMeters (WGS84)."""
    geom = closure.get("geometry")
    if not geom:
        raise invalid(f"Closure {closure.get('id')} has no geometry.", code="NO_GEOMETRY")
    return buffer_m(from_geojson(geom), float(closure.get("bufferMeters") or 30))


# --- Timpark features in the buffer -------------------------------------------------


@lru_cache(maxsize=1)
def _parking_index() -> tuple[list[dict], list[BaseGeometry], STRtree]:
    feats = load_parking().features
    geoms = [shape(f["geometry"]) for f in feats]
    return feats, geoms, STRtree(geoms)


def _ref(feature: dict) -> ParkingFeatureRef:
    p = feature["properties"]
    return ParkingFeatureRef(id=p["id"], name=p["name"], tariff=p["tariff"], geometry=feature["geometry"])


def features_in(area: BaseGeometry) -> tuple[list[ParkingFeatureRef], list[ParkingFeatureRef]]:
    """(streets, lots) of Timpark that intersect a WGS84 area, in the city's order."""
    feats, geoms, tree = _parking_index()
    hits = sorted(int(i) for i in tree.query(area, predicate="intersects"))
    streets = [_ref(feats[i]) for i in hits if feats[i]["properties"]["kind"] == "street"]
    lots = [_ref(feats[i]) for i in hits if feats[i]["properties"]["kind"] == "lot"]
    return streets, lots


# --- Park & Ride ------------------------------------------------------------------------


def centre_point() -> Point | None:
    """Piața Victoriei from OSM (centroid of the ways with that name)."""
    try:
        return osm_ways.place_point(CENTRE_NAME)
    except FileNotFoundError:
        return None


def _line_ends() -> dict[str, list[str]]:
    """stopId -> routes for which it is the first or last stop of a direction."""
    ends: dict[str, list[str]] = {}
    for (route_id, _direction), pattern in sorted(gtfs.stop_patterns().items()):
        if not pattern.stop_ids:
            continue
        for stop_id in (pattern.stop_ids[0], pattern.stop_ids[-1]):
            routes = ends.setdefault(str(stop_id), [])
            if route_id not in routes:
                routes.append(route_id)
    return ends


def _route_sort_key(route_id: str) -> tuple:
    short = (load_network().route_by_id.get(route_id) or {}).get("shortName", route_id)
    digits = "".join(c for c in short if c.isdigit())
    return (short.rstrip("0123456789"), int(digits) if digits else -1, short)


@lru_cache(maxsize=1)
def all_park_and_ride() -> tuple[ParkAndRide, ...]:
    """Every P&R option in the city (SPEC §6.6), farthest from the centre first."""
    centre = centre_point()
    if centre is None:
        return ()
    net = load_network()
    feats, geoms, _tree = _parking_index()
    lots = [(feats[i]["properties"]["id"], to_metric(geoms[i]))
            for i in range(len(feats)) if feats[i]["properties"]["kind"] == "lot"]
    if not lots:
        return ()
    lot_tree = STRtree([g for _, g in lots])
    centre_m = to_metric(centre)
    out = []
    for stop_id, route_ids in _line_ends().items():
        stop = net.stop_by_id.get(stop_id)
        if stop is None:
            continue
        stop_m = to_metric(Point(stop["location"]))
        from_centre = stop_m.distance(centre_m)
        if from_centre <= MIN_CENTRE_METERS:
            continue
        j = int(lot_tree.nearest(stop_m))
        walk = stop_m.distance(lots[j][1])
        if walk > MAX_LOT_METERS:
            continue
        out.append((from_centre, ParkAndRide(stopId=stop_id, name=stop["name"],
                                             routeIds=sorted(route_ids, key=_route_sort_key),
                                             lotId=lots[j][0], walkMeters=round(walk))))
    out.sort(key=lambda t: (-t[0], t[1].stopId))
    return tuple(p for _, p in out)


def _lost_pairs(closure: dict, analysis: dict | None) -> tuple[set[str], set[tuple[str, str]]]:
    """(routes suspended as a whole line, (stopId, routeId) pairs the closure suspends)."""
    from app.m1_disruption.impact import counts_as_lost

    whole = {a["routeId"] for a in closure.get("routeActions") or []
             if a.get("action") == "suspended" and not a.get("fromStopId") and not a.get("toStopId")
             and a.get("directionId") is None}
    pairs = {(str(r["stopId"]), r["routeId"]) for r in (analysis or {}).get("stops") or [] if counts_as_lost(r)}
    return whole, pairs


def _analysis(closure_id: str) -> dict | None:
    from app.m1_disruption.analysis import get_analysis

    a = get_analysis(closure_id)
    return a.model_dump(mode="json") if a is not None else None


def options_for(closure: dict, analysis: dict | None) -> list[ParkAndRide]:
    """The city's P&R options, each with only the lines that still run from it during the closure.

    Every option in the city is offered (there are few, and a driver parks at the edge
    whatever line the works hit); a line the closure suspends at that stop is removed,
    and an option with no line left is dropped.
    """
    whole, lost = _lost_pairs(closure, analysis)
    out = []
    for p in all_park_and_ride():
        keep = [r for r in p.routeIds if r not in whole and (p.stopId, r) not in lost]
        if keep:
            out.append(p.model_copy(update={"routeIds": keep}))
    return out


def park_and_ride_options(closure_id: str) -> list[ParkAndRide]:
    """For the decide agent's park_and_ride mitigation."""
    return options_for(load_closure(closure_id), _analysis(closure_id))


# --- the response ---------------------------------------------------------------------


def provenance_list(with_pr: bool) -> list:
    p = load_parking().provenance
    out = [p.model_copy(update={"note": "id-urile și culorile tarifelor Timpark, neschimbate / "
                                        "Timpark ids and tariff colours unchanged"})]
    if with_pr:
        out.append(gtfs.feed().provenance.model_copy(update={
            "note": "capete de linie: prima / ultima stație a traseului cel mai frecvent / "
                    "line ends: first / last stop of the most common trip pattern"}))
        osm = prov.from_sources("osm") or prov.provenance("OpenStreetMap", now(), "https://www.openstreetmap.org")
        out.append(osm.model_copy(update={"note": f"P&R: capăt de linie la peste 3 km de {CENTRE_NAME} (OSM) și "
                                                  f"o parcare Timpark la cel mult 500 m în linie dreaptă; "
                                                  f"{PR_LABEL}"}))
    return out


def parking_impact(closure_id: str) -> ParkingImpact:
    closure = load_closure(closure_id)
    streets, lots = features_in(closure_buffer(closure))
    pr = options_for(closure, _analysis(closure_id))
    return ParkingImpact(closureId=closure_id, streetsAffected=streets, lotsAffected=lots, parkAndRide=pr,
                         provenance=provenance_list(with_pr=True))


def clear_caches() -> None:
    _parking_index.cache_clear()
    all_park_and_ride.cache_clear()
