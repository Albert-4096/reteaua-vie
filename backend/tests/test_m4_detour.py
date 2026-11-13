"""Detour load (Braess F1) and spillover (F2) on the real prepared cases and OSM extract.

The results go through the job cache, so after `make precompute` these tests take
under a second; on a cold cache the three cases take about a minute.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString

from tests.conftest import DATA_DIR, needs_data

from app.common import state
from app.models.v2 import DetourLoad

HAS_OSM = (DATA_DIR / "osm" / "timisoara.osm.pbf").is_file()
pytestmark = [needs_data, pytest.mark.skipif(not HAS_OSM, reason="no OSM extract")]

CASES = ["cl_20261108_16dec", "cl_20261107_e3", "cl_20261102_mocioni"]


def _closure(cid: str) -> dict:
    c = state.read("closures", cid)
    if c is None:
        pytest.skip(f"prepared case {cid} not built (make precompute)")
    return c


@pytest.fixture(scope="module")
def loads() -> dict[str, DetourLoad]:
    from app.m4_access import detour
    from app.m4_access.spillover import with_spillover

    out = {}
    for cid in CASES:
        out[cid] = with_spillover(_closure(cid), detour.compute_for(cid))
    return out


def test_label_and_wording(loads):
    for r in loads.values():
        assert r.label.ro.startswith("Structura rețelei de străzi, nu volume de trafic")
        assert "risc de încetinire" in r.label.ro
        assert "vor fi încetinite" not in r.label.ro
        assert r.provenance and any("OpenStreetMap" in p.source for p in r.provenance)


def test_top_edges_gain_and_are_open(loads):
    from app.common.geo import from_geojson, to_metric

    for cid, r in loads.items():
        assert 1 <= len(r.edges) <= 5, cid
        changes = [e.centralityAfter - e.centralityBefore for e in r.edges]
        assert all(c > 0 for c in changes), cid                     # edges that take the detour
        assert changes == sorted(changes, reverse=True), cid        # ranked by absolute change
        for e in r.edges:
            assert e.centralityBefore > 0
            assert e.changePct == pytest.approx((e.centralityAfter - e.centralityBefore) / e.centralityBefore * 100, rel=0.01, abs=0.1)
            lon, lat = e.geometry.coordinates[0][:2]
            assert 21.0 < lon < 21.5 and 45.6 < lat < 45.9           # GeoJSON [lon, lat]
        # an edge is never the closed street itself (fully inside the buffer)
        c = _closure(cid)
        buf = to_metric(from_geojson(c["geometry"])).buffer(float(c["bufferMeters"]))
        for e in r.edges:
            assert not buf.contains(to_metric(LineString(e.geometry.coordinates))), (cid, e.name)


def test_routes_slowed_risk_excludes_own_routes(loads):
    from app.m4_access.detour import own_routes

    for cid, r in loads.items():
        own = own_routes(_closure(cid))
        on_edges = set().union(*(set(e.routeIdsOnEdge) for e in r.edges))
        assert set(r.routesSlowedRisk) == on_edges - own, cid
        assert not set(r.routesSlowedRisk) & own


def test_e3_detour_goes_on_banatul(loads):
    # Str. Ardealului closed: the street network sends the through paths to Str. Banatul
    names = [e.name for e in loads["cl_20261107_e3"].edges]
    assert "Strada Banatul" in names
    assert "R_AB_E3" not in loads["cl_20261107_e3"].routesSlowedRisk


def test_spillover_only_with_a_recording(loads):
    assert loads["cl_20261108_16dec"].spillover is None      # 8 Nov: before the recording started
    assert loads["cl_20261107_e3"].spillover is None         # ended 13 Nov 00:00
    sp = loads["cl_20261102_mocioni"].spillover               # runs during the recording
    assert sp is not None
    assert sp.label.ro.lower().startswith("comparație cu restul rețelei, nu efectul închiderii")
    assert sp.hours > 0 and sp.from_ < sp.to
    assert sp.from_ >= "2026-11-13"
    assert any("înregistrarea noastră" in p.source for p in loads["cl_20261102_mocioni"].provenance)


def test_stable_numbers_on_recompute():
    """Fixed seed: a fresh computation gives the same edges and values (E3: ~8 s)."""
    from app.m4_access import detour

    c = _closure("cl_20261107_e3")
    t = time.perf_counter()
    a = detour.compute_detour_load(c)
    elapsed = time.perf_counter() - t
    b = detour.cached_for("cl_20261107_e3") or detour.compute_detour_load(c)
    assert [(e.name, e.centralityBefore, e.centralityAfter) for e in a.edges] == \
           [(e.name, e.centralityBefore, e.centralityAfter) for e in b.edges]
    assert elapsed < 60


def test_api_detour_load(loads):
    from app.main import app

    client = TestClient(app)
    r = client.get("/api/closures/cl_20261102_mocioni/detour-load")
    assert r.status_code == 200
    body = DetourLoad.model_validate(r.json())
    assert body.spillover is not None and "from" in r.json()["spillover"]
    r = client.get("/api/closures/nope/detour-load")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
