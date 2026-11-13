"""M5 bike: the LTS table (SPEC §6.5), bike impact on the real prepared cases, the bike layer."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString

from tests.conftest import DATA_DIR, needs_data

from app.m5_bike.lts import is_bike_way, lts, maxspeed

HAS_OSM = (DATA_DIR / "osm" / "timisoara.osm.pbf").is_file()
needs_osm = pytest.mark.skipif(not HAS_OSM, reason="no OSM extract")

CASES = ["cl_20261108_16dec", "cl_20261107_e3", "cl_20261102_mocioni"]


# --- the LTS table, row by row -------------------------------------------------------------


@pytest.mark.parametrize("tags, expected", [
    ({"highway": "cycleway"}, 1),
    ({"highway": "secondary", "cycleway:right": "track"}, 1),
    ({"highway": "path", "bicycle": "designated"}, 1),
    ({"highway": "residential", "cycleway": "lane", "maxspeed": "30"}, 2),
    ({"highway": "tertiary", "cycleway:both": "lane", "maxspeed": "30"}, 2),
    ({"highway": "residential", "maxspeed": "30"}, 2),
    ({"highway": "secondary", "cycleway": "lane", "maxspeed": "50"}, 3),
    ({"highway": "secondary", "cycleway": "lane"}, 3),                 # maxspeed missing: 50
    ({"highway": "tertiary", "cycleway:left": "lane", "maxspeed": "RO:urban"}, 3),
    ({"highway": "secondary", "maxspeed": "70"}, 4),
    ({"highway": "residential", "cycleway": "lane", "maxspeed": "60"}, 4),
    ({"highway": "primary"}, 4),
    ({"highway": "trunk", "maxspeed": "50"}, 4),
    ({"highway": "primary", "cycleway": "lane", "maxspeed": "50"}, 3),  # a lane is a facility
    ({"highway": "unknown_class"}, None),
    ({"highway": "track"}, None),
    # gaps filled (README, marked *)
    ({"highway": "footway", "bicycle": "designated"}, 1),
    ({"highway": "footway", "bicycle": "yes"}, 2),
    ({"highway": "path"}, 2),
    ({"highway": "residential"}, 3),
    ({"highway": "living_street"}, 2),
    ({"highway": "tertiary", "maxspeed": "50"}, 3),
    ({"highway": "residential", "cycleway": "shared_lane", "maxspeed": "50"}, 3),
    # not in the bike network
    ({"highway": "footway"}, None),
    ({"highway": "primary", "bicycle": "no"}, None),
    ({"highway": "motorway"}, None),
])
def test_lts_table(tags, expected):
    assert lts(tags) == expected


def test_maxspeed_words_and_bike_ways():
    assert maxspeed({"maxspeed": "RO:urban"}) == 50
    assert maxspeed({"maxspeed": "RO:rural"}) == 90
    assert maxspeed({"maxspeed": "signals"}) is None
    assert is_bike_way({"highway": "cycleway"})
    assert is_bike_way({"highway": "residential", "cycleway:right": "lane"})
    assert is_bike_way({"highway": "footway", "bicycle": "designated"})
    assert not is_bike_way({"highway": "residential"})
    assert not is_bike_way({"highway": "footway", "bicycle": "yes"})


def test_table_is_in_the_module_docstring():
    import app.m5_bike.lts as mod

    for row in ("| 1 | `highway=cycleway`", "| 4 | a road with maxspeed > 50", "unknown: then `null`"):
        assert row in mod.__doc__


# --- bike impact on the real prepared cases --------------------------------------------------


@pytest.fixture(scope="module")
def impacts():
    from app.common import state
    from app.m5_bike import bike

    out = {}
    for cid in CASES:
        if state.read("closures", cid) is None:
            pytest.skip("prepared cases not built (make precompute)")
        out[cid] = bike.bike_impact(cid)
    return out


def _buffer(cid: str):
    from app.common import state
    from app.common.geo import from_geojson, to_metric

    c = state.read("closures", cid)
    return to_metric(from_geojson(c["geometry"])).buffer(float(c["bufferMeters"]))


def _cost(r) -> float:
    from app.m5_bike.bike import LTS_FACTOR

    return sum(p.lengthMeters * LTS_FACTOR[p.lts] for p in r.detourStress)


@needs_data
@needs_osm
def test_lanes_inside_buffer(impacts):
    from app.common.geo import to_metric

    # Mocioni: the works run along Bd. 16 Decembrie 1989, which has mapped bike ways (the hero is
    # drawn as 15 m at the Piața Maria junction since T11 and has none in its buffer)
    moc = impacts["cl_20261102_mocioni"]
    assert moc.lanesAffected, "Bd. 16 Decembrie 1989 at Piața Mocioni has mapped bike ways"
    buf = _buffer("cl_20261102_mocioni").buffer(0.5)
    for lane in moc.lanesAffected:
        assert lane.osmId.startswith("way/") and lane.lengthMeters > 0
        assert buf.contains(to_metric(LineString(lane.geometry.coordinates)))


@needs_data
@needs_osm
def test_detour_avoids_the_closure(impacts):
    from app.common.geo import to_metric

    for cid, r in impacts.items():
        if cid == "cl_20261108_16dec":   # 15 m closure (T11): no bike way to detour from
            continue
        assert r.detourStress, cid
        assert all(p.lts in (1, 2, 3, 4, None) for p in r.detourStress)
        buf = _buffer(cid)
        inside = sum(to_metric(LineString(p.geometry.coordinates)).intersection(buf).length for p in r.detourStress)
        total = sum(p.lengthMeters for p in r.detourStress)
        assert inside < 0.25 * total, (cid, inside, total)    # it may cross the street, not ride along it


@needs_data
@needs_osm
def test_missing_osm_is_unknown_not_none(impacts):
    e3 = impacts["cl_20261107_e3"]
    assert e3.lanesAffected == []
    note = e3.provenance[0].note
    assert "necunoscut" in note
    assert any("OpenStreetMap" in p.source or "OSM" in (p.note or "") for p in e3.provenance)


@needs_data
@needs_osm
def test_temporary_lane_lowers_the_detour_stress(impacts):
    from app.common import state
    from app.m5_bike import bike

    closure = state.read("closures", "cl_20261107_e3")
    lane = closure["geometry"]                  # a protected lane on the closed street itself
    with_lane = bike.bike_impact_with_lane("cl_20261107_e3", lane)
    assert _cost(with_lane) < _cost(impacts["cl_20261107_e3"])
    assert any(p.lts == 1 for p in with_lane.detourStress)
    assert "pistă temporară" in with_lane.provenance[0].note
    same = bike.bike_impact_for(closure, [lane])
    assert _cost(same) == pytest.approx(_cost(with_lane))


@needs_data
@needs_osm
def test_fast_once_warm(impacts):
    from app.m5_bike import bike

    t = time.perf_counter()
    bike.bike_impact("cl_20261108_16dec")
    assert time.perf_counter() - t < 3.0     # SPEC §10: a live draw gets bike numbers in < 3 s


# --- layer and API -------------------------------------------------------------------------


@needs_data
@needs_osm
def test_bike_layer_and_api(impacts):
    from app.main import app
    from app.m5_bike.layers import bike_layer
    from app.models.v2 import BikeImpact, LayerCollection

    full = LayerCollection.model_validate(bike_layer())
    kinds = {f.properties["kind"] for f in full.features}
    assert {"lane", "parking", "share_station"} <= kinds
    assert all(f.properties["lts"] in (1, 2, 3, 4) for f in full.features if f.properties["kind"] == "lane")
    part = bike_layer((21.20, 45.74, 21.23, 45.76))
    assert 0 < len(part["features"]) < len(full.features)

    client = TestClient(app)
    r = client.get("/api/closures/cl_20261108_16dec/bike")
    assert r.status_code == 200
    BikeImpact.model_validate(r.json())
    assert client.get("/api/closures/nope/bike").status_code == 404
    r = client.get("/api/layers/bike?bbox=21.20,45.74,21.23,45.76")
    assert r.status_code == 200 and r.json()["layer"] == "bike"
