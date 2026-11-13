"""M2 routing: a trip that avoids suspended stops, as a service for CityApp (SPEC §6.2).

- Router: R5 (r5py) on the patched GTFS of every closure active at `at`
  (status analyzed or published, window contains `at`, lost rows after the clerk's
  decisions). Never GTFS-RT: routers read alerts as text only.
- Settings: walk 4.8 km/h, at most 1 km of walking (13 min), at most 2 transfers
  (3 rides), departure = `at` (default DEMO_NOW); of the options R5 finds for the
  10-minute departure window, the one that arrives first.
- avoidedStopIds: suspended (stop, route) pairs that the baseline plan (same query on
  the unpatched timetable) boards or leaves at.
- No step-free or bike-and-ride claims (the GTFS has no wheelchair data and
  bikes_allowed = 2 on every trip).

Public:
    active_closures(at) -> [(closure, lost)]
    plan_route(from_lonlat, to_lonlat, at) -> RoutePlan
    demo_pair() -> (from, to, at)      SPEC: a suspended line 4 stop of the hero case → Piața Victoriei
    warm_demo_route() -> RoutePlan
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

import pandas as pd

from app.common import provenance as prov
from app.common import state
from app.common.city import load_network, route_mode
from app.common.errors import not_found, unavailable
from app.common.timeutil import iso, parse_iso
from app.config import TZ, get_settings, now
from app.m1_disruption import impact as imp
from app.m4_access import layers, patched_gtfs, r5
from app.models.base import Provenance
from app.models.v2 import RouteLeg, RoutePlan

log = logging.getLogger("reteaua_vie.m2")

ROUTE_VERSION = 1
MAX_WALK_MIN = 13           # 1 km at 4.8 km/h (SPEC §6.2)
MAX_RIDES = 3               # at most 2 transfers
MAX_TRIP_MIN = 120
ACTIVE_STATUSES = ("analyzed", "published")

HERO = "cl_20261108_16dec"
DEMO_AT = "2026-11-08T12:00:00+02:00"
DEMO_ROUTE = "R_TV_4"
DEMO_PLACE = "Piața Victoriei"


# --- which closures ------------------------------------------------------------------------


Override = dict[str, dict]   # closure id -> a hypothetical analysis (pre-warm of planned decisions)


def active_closures(at: datetime, override: Override | None = None) -> list[tuple[dict, set]]:
    """Stored closures whose window contains `at`, with their lost rows (non-empty only).

    `override` replaces a closure's stored analysis (used only to pre-warm decisions a clerk
    is expected to take; nothing is written).
    """
    out = []
    for c in state.list_all("closures"):
        if c.get("status") not in ACTIVE_STATUSES or not c.get("window"):
            continue
        try:
            if not parse_iso(c["window"]["start"]) <= at < parse_iso(c["window"]["end"]):
                continue
            if override and c["id"] in override:
                lost = {imp.row_key(r) for r in override[c["id"]]["stops"] if imp.counts_as_lost(r)}
            else:
                _, lost = patched_gtfs.lost_rows(c["id"])
        except Exception:  # a closure without an analysis does not change the timetable
            continue
        if lost:
            out.append((c, lost))
    return sorted(out, key=lambda it: it[0]["id"])


def closures_fingerprint(at: datetime, override: Override | None = None) -> str:
    """Hash of what the route at `at` depends on: the active closures' windows and lost rows."""
    parts = [[c["id"], c["window"], sorted(lost)] for c, lost in active_closures(at, override)]
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


# --- itineraries ------------------------------------------------------------------------------


@dataclass
class Option:
    legs: list[dict]
    depart: datetime
    arrive: datetime


def _local(ts) -> datetime:
    return pd.Timestamp(ts).to_pydatetime().replace(tzinfo=TZ)


def _coords(geom) -> list[list[float]]:
    pts = [[round(x, 6), round(y, 6)] for x, y in geom.coords] if geom is not None and not geom.is_empty else []
    if len(pts) == 1:
        pts.append(list(pts[0]))
    return pts


def _options(gdf) -> list[Option]:
    out = []
    if gdf is None or len(gdf) == 0:
        return out
    for _, g in gdf.groupby("option", sort=True):
        g = g.sort_values("segment")
        legs = []
        for row in g.itertuples(index=False):
            if pd.isna(row.departure_time) or pd.isna(row.travel_time):
                continue
            dep = _local(row.departure_time)
            arr = dep + pd.Timedelta(row.travel_time).to_pytimedelta()
            mode = str(row.transport_mode).split(".")[-1].upper()
            transit = mode not in ("WALK",)
            rid = str(row.route_id) if transit and isinstance(row.route_id, str) and row.route_id else None
            legs.append({
                "mode": route_mode(rid) if rid else "walk",
                "routeId": rid,
                "fromStopId": str(row.start_stop_id) if transit and isinstance(row.start_stop_id, str) else None,
                "toStopId": str(row.end_stop_id) if transit and isinstance(row.end_stop_id, str) else None,
                "departAt": dep, "arriveAt": arr,
                "geometry": {"type": "LineString", "coordinates": _coords(row.geometry)},
            })
        legs = [lg for lg in legs if len(lg["geometry"]["coordinates"]) >= 2]
        if legs:
            out.append(Option(legs, legs[0]["departAt"], legs[-1]["arriveAt"]))
    return out


def best_option(gdf) -> Option | None:
    """The option that arrives first; then the fewest rides; then the latest start."""
    opts = _options(gdf)
    if not opts:
        return None
    return min(opts, key=lambda o: (o.arrive, sum(1 for lg in o.legs if lg["routeId"]), -o.depart.timestamp()))


def avoided_stops(baseline: Option | None, lost: frozenset) -> list[str]:
    """Stops the baseline plan boards or leaves at, on a route that is suspended there."""
    if baseline is None:
        return []
    pairs = {(s, r) for s, r, _ in lost}
    out: list[str] = []
    for lg in baseline.legs:
        for s in (lg["fromStopId"], lg["toStopId"]):
            if s and lg["routeId"] and (s, lg["routeId"]) in pairs and s not in out:
                out.append(s)
    return out


def _r5_provenance(pf: patched_gtfs.PatchedFeed | None, closures: list[dict], at: datetime) -> Provenance:
    names = ", ".join(c["id"] for c in closures) or "niciuna / none"
    note = (f"plecare {iso(at)}; mers pe jos 4,8 km/h, cel mult 1 km; cel mult 2 transferuri; "
            f"orar fără opririle suspendate ale lucrărilor active: {names}")
    if pf is not None:
        note += f" ({len(pf.lost)} perechi stație–linie, {pf.trips_cancelled} curse anulate)"
    note += ". Fără garanții de accesibilitate (GTFS fără date pentru scaun rulant) și fără bicicletă la bord."
    return prov.provenance("Rețeaua Vie: R5 (Conveyal, r5py) pe GTFS cu opririle suspendate scoase",
                           now(), "https://r5py.readthedocs.io", None, note)


def plan_route(frm: tuple[float, float], to: tuple[float, float], at: datetime | None = None,
               override: Override | None = None) -> RoutePlan:
    at = (at or now()).astimezone(TZ)
    if not r5.available():
        raise unavailable("Routing engine (Java / r5py) is not available.", code="ROUTER_UNAVAILABLE")
    items = active_closures(at, override)
    base_src, _ = patched_gtfs.base_feed(at)
    base = patched_gtfs.clean_base(base_src)
    pf = patched_gtfs.patched_combined(items, at) if items else None
    kw = dict(max_minutes=MAX_TRIP_MIN, max_walk_minutes=MAX_WALK_MIN, max_rides=MAX_RIDES)
    after = best_option(r5.itineraries(pf.path if pf else base, frm, to, at, **kw))
    if after is None:
        raise not_found("No trip found within 2 hours, 1 km of walking and 2 transfers.", code="NO_ROUTE")
    baseline = best_option(r5.itineraries(base, frm, to, at, **kw)) if pf else after
    legs = [RouteLeg(mode=lg["mode"], routeId=lg["routeId"], fromStopId=lg["fromStopId"], toStopId=lg["toStopId"],
                     departAt=iso(lg["departAt"]), arriveAt=iso(lg["arriveAt"]), geometry=lg["geometry"])
            for lg in after.legs]
    tt = imp.timetable_for(at)
    provenance = [tt.provenance, layers.osm_provenance(), _r5_provenance(pf, [c for c, _ in items], at)]
    return RoutePlan(**{"from": [frm[0], frm[1]]}, to=[to[0], to[1]], at=iso(at), legs=legs,
                     durationMinutes=round((after.arrive - after.depart).total_seconds() / 60, 1),
                     avoidedStopIds=avoided_stops(baseline, pf.lost if pf else frozenset()),
                     provenance=provenance)


# --- the demo pair (SPEC §6.2) ----------------------------------------------------------------


@lru_cache(maxsize=1)
def place_location(name: str) -> tuple[float, float]:
    """Centroid of the OSM object(s) with this name (a place=square first), cached in $DATA_DIR/cache."""
    cache = get_settings().cache_dir / "osm_places_v1.json"
    known = json.loads(cache.read_text()) if cache.is_file() else {}
    if name in known:
        return tuple(known[name])
    import pyrosm  # noqa: PLC0415

    gdf = pyrosm.OSM(str(r5.osm_pbf())).get_data_by_custom_criteria(
        custom_filter={"name": [name]}, filter_type="keep", keep_nodes=True, keep_ways=True, keep_relations=True)
    if gdf is None or len(gdf) == 0:
        raise not_found(f"No OSM object named {name!r}.")
    squares = gdf[gdf["tags"].astype(str).str.contains('"place":"square"')]
    pick = squares if len(squares) else gdf
    c = pick.geometry.union_all().centroid
    known[name] = [round(c.x, 6), round(c.y, 6)]
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps(known, ensure_ascii=False))
    tmp.replace(cache)
    return tuple(known[name])


def demo_pair() -> tuple[tuple[float, float], tuple[float, float], datetime, str]:
    """From the hero case's line 4 stop with the most departures lost and no other service → Piața Victoriei."""
    closure, lost = patched_gtfs.lost_rows(HERO)
    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    tt = imp.timetable_for(start)
    counts = tt.counts(start, end)
    l4 = {k for k in lost if k[1] == DEMO_ROUTE}
    if not l4:
        raise not_found("The hero case has no suspended line 4 stop.", code="NO_DEMO_STOP")
    by_stop: dict[str, int] = {}
    for k in l4:
        by_stop[k[0]] = by_stop.get(k[0], 0) + counts.get(k, 0)
    still_served = {s for (s, r, d), n in counts.items() if n and (s, r, d) not in lost}
    stop = sorted(by_stop, key=lambda s: (s in still_served, -by_stop[s], s))[0]
    n = load_network()
    loc = next((s["location"] for s in n.stops if s["id"] == stop), None)
    if loc is None:
        raise not_found(f"Stop {stop} is not in the network.")
    return (loc[0], loc[1]), place_location(DEMO_PLACE), parse_iso(DEMO_AT), stop


def route_key(frm: tuple[float, float], to: tuple[float, float], at: datetime,
              override: Override | None = None) -> str:
    return (f"route:v{ROUTE_VERSION}:{frm[0]:.5f},{frm[1]:.5f}:{to[0]:.5f},{to[1]:.5f}:"
            f"{iso(at.astimezone(TZ))}:{closures_fingerprint(at, override)}")


def warm_demo_route(override: Override | None = None) -> RoutePlan:
    from app.common.jobs import compute_and_cache

    frm, to, at, _ = demo_pair()
    return compute_and_cache(route_key(frm, to, at, override), lambda: plan_route(frm, to, at, override))

