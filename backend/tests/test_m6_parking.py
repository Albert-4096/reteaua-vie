"""M6 parking on the real data: Timpark features in the buffer, Park & Ride rule (SPEC §6.6)."""

from __future__ import annotations

import json
import threading

import pytest
from shapely.geometry import Point, shape

from app.common import gtfs, state
from app.common.geo import haversine_m, to_metric
from tests.conftest import DATA_DIR, needs_data

HERO = "cl_20261108_16dec"
E3 = "cl_20261107_e3"
MOCIONI = "cl_20261102_mocioni"   # runs along Bd. 16 Decembrie 1989 (the hero is 15 m at a junction since T11)


def _raw_parking() -> dict[str, dict]:
    raw = json.loads((DATA_DIR / "city-api-2026-11-13" / "parking.json").read_text(encoding="utf-8"))
    return {f["id"]: f for f in raw["features"]}


def _stored(closure_id: str) -> dict:
    c = state.read("closures", closure_id)
    if c is None:
        pytest.skip(f"{closure_id} not prepared (run make precompute)")
    return c


@needs_data
def test_hero_streets_keep_city_ids_and_tariffs():
    from app.m6_parking import parking

    closure = _stored(MOCIONI)
    impact = parking.parking_impact(MOCIONI)
    raw = _raw_parking()
    buf = parking.closure_buffer(closure)
    assert impact.streetsAffected, "the Mocioni works run through Timpark streets"
    names = {s.name for s in impact.streetsAffected}
    assert "Bulevardul 16 Decembrie 1989" in names
    for ref in impact.streetsAffected + impact.lotsAffected:
        city = raw[ref.id]
        assert (ref.name, ref.tariff) == (city.get("name") or "", city.get("tariff") or "")
        assert [list(map(float, c)) for c in city["coordinates"]] == \
            (ref.geometry["coordinates"][0] if ref.geometry["type"] == "Polygon" else ref.geometry["coordinates"])
        assert shape(ref.geometry).intersects(buf)
    assert {s.id for s in impact.streetsAffected} <= {k for k, f in raw.items() if f["kind"] == "street"}
    # every Timpark street that crosses the buffer is listed (none missed)
    expected = {k for k, f in raw.items() if f["kind"] == "street"
                and shape({"type": "LineString", "coordinates": f["coordinates"]}).intersects(buf)}
    assert {s.id for s in impact.streetsAffected} == expected
    assert impact.provenance and "Timpark" in impact.provenance[0].source


@needs_data
def test_e3_is_outside_timpark():
    from app.m6_parking import parking

    _stored(E3)
    impact = parking.parking_impact(E3)
    assert impact.streetsAffected == [] and impact.lotsAffected == []
    assert impact.provenance


@needs_data
def test_park_and_ride_follows_the_spec_rule():
    from app.m3_notices import osm_ways
    from app.m6_parking import parking

    options = parking.all_park_and_ride()
    assert options, "the city has line ends near Timpark lots"
    centre = osm_ways.place_point("Piața Victoriei")
    assert centre is not None
    raw = _raw_parking()
    ends: dict[str, set[str]] = {}
    for (rid, _d), p in gtfs.stop_patterns().items():
        for s in (p.stop_ids[0], p.stop_ids[-1]):
            ends.setdefault(str(s), set()).add(rid)
    stops = json.loads((DATA_DIR / "city-api-2026-11-13" / "transit-network.json").read_text())["stops"]
    loc = {str(s["id"]): (float(s["lon"]), float(s["lat"])) for s in stops}
    for o in options:
        assert set(o.routeIds) == ends[o.stopId]                     # first or last stop of those lines
        lon, lat = loc[o.stopId]
        assert haversine_m(lon, lat, centre.x, centre.y) > 3000      # far from Piața Victoriei
        lot = raw[o.lotId]
        assert lot["kind"] == "lot"
        lot_geom = shape({"type": "Polygon", "coordinates": [lot["coordinates"]]})
        walk = to_metric(Point(lon, lat)).distance(to_metric(lot_geom))
        assert o.walkMeters == round(walk) and walk <= 500
    # stops that pass the rule but are not listed: none
    listed = {o.stopId for o in options}
    for stop_id in ends:
        if stop_id in listed or stop_id not in loc:
            continue
        lon, lat = loc[stop_id]
        if haversine_m(lon, lat, centre.x, centre.y) <= 3000:
            continue
        pt = to_metric(Point(lon, lat))
        near = min(pt.distance(to_metric(shape({"type": "Polygon", "coordinates": [f["coordinates"]]})))
                   for f in raw.values() if f["kind"] == "lot")
        assert near > 500, stop_id


@needs_data
def test_park_and_ride_drops_lines_the_closure_suspends():
    from app.m6_parking import parking

    options = parking.all_park_and_ride()
    target = options[0]
    gone = target.routeIds[0]
    closure = {"id": "cl_test", "routeActions": [{"routeId": gone, "directionId": None, "action": "suspended",
                                                  "fromStopId": None, "toStopId": None}]}
    out = {o.stopId: o for o in parking.options_for(closure, None)}
    for o in options:
        left = [r for r in o.routeIds if r != gone]
        if left:
            assert out[o.stopId].routeIds == left
        else:
            assert o.stopId not in out


@needs_data
def test_parking_endpoint(client):
    _stored(MOCIONI)
    r = client.get(f"/api/closures/{MOCIONI}/parking")
    assert r.status_code == 200, r.text
    from app.models.v2 import ParkingImpact

    body = ParkingImpact.model_validate(r.json())
    assert body.closureId == MOCIONI and body.streetsAffected and body.provenance
    assert any("fără date de ocupare" in (p.note or "") for p in body.provenance)
    assert client.get("/api/closures/no_such_closure/parking").status_code == 404
    # let the routers' background warm-ups finish: a short run must not exit while they are in C code
    for t in threading.enumerate():
        if t.name.endswith("-warm"):
            t.join(180)


@needs_data
def test_warm_runs_on_the_prepared_cases():
    from app.m6_parking.warm import warm

    warm([HERO, E3])
