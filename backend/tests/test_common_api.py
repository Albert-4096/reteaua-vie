"""The seven D-011 endpoints answer from real data, in the contract shapes."""

from __future__ import annotations

from pydantic import TypeAdapter

from app import models as m
from app.common import state
from tests.conftest import needs_data


@needs_data
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    h = m.Health.model_validate(r.json())
    assert h.ok and h.feedVersion


@needs_data
def test_network_has_lonlat_locations(client):
    net = m.Network.model_validate(client.get("/api/network").json())
    assert len(net.routes) > 0 and len(net.stops) > 0 and len(net.paths) > 0
    s = net.stops[0]
    assert s.location == [s.lon, s.lat]
    # Timișoara: lon ~21.2, lat ~45.75, so GeoJSON order is lon first
    assert 20.5 < net.paths[0].geometry.coordinates[0][0] < 22
    assert net.provenance and net.provenance[0].version == net.feedVersion


@needs_data
def test_zones(client):
    z = m.ZoneCollection.model_validate(client.get("/api/zones").json())
    slugs = [f.properties["slug"] for f in z.features]
    assert len(slugs) == len(set(slugs)) > 0


@needs_data
def test_parking_layer_and_bbox(client):
    full = m.LayerCollection.model_validate(client.get("/api/layers/parking").json())
    part = m.LayerCollection.model_validate(
        client.get("/api/layers/parking", params={"bbox": "21.21,45.74,21.23,45.76"}).json())
    assert full.layer == "parking" and 0 < len(part.features) < len(full.features)
    assert client.get("/api/layers/parking", params={"bbox": "1,2"}).status_code == 422


@needs_data
def test_live_vehicles_filter(client):
    allv = m.LayerCollection.model_validate(client.get("/api/live/vehicles").json())
    assert allv.layer == "vehicles" and allv.provenance
    if allv.features:
        rid = allv.features[0].properties["routeId"]
        one = client.get("/api/live/vehicles", params={"routeId": rid}).json()
        assert all(f["properties"]["routeId"] == rid for f in one["features"])


def test_cases(client):
    cases = TypeAdapter(list[m.CaseSummary]).validate_python(client.get("/api/cases").json())
    assert [c.id for c in cases] == ["case_16dec", "case_e3", "case_mocioni"]


def test_closures_list_reads_state(client, isolated_state):
    assert client.get("/api/closures").json() == []
    closure = {
        "id": "cl_test_1", "status": "draft", "createdAt": "2026-11-13T18:00:00+02:00",
        "title": {"ro": "Test", "en": "Test"}, "kind": "drawn", "geometry": None,
        "bufferMeters": 30, "direction": "both",
        "window": {"start": "2026-11-08T10:00:00+02:00", "end": "2026-11-08T18:00:00+02:00"},
        "routeIds": ["R_TV_4"],
    }
    state.write("closures", "cl_test_1", m.Closure.model_validate(closure))
    rows = client.get("/api/closures").json()
    assert len(rows) == 1 and rows[0]["stopsSuspended"] is None and rows[0]["routeIds"] == ["R_TV_4"]
    assert client.get("/api/closures", params={"status": "published"}).json() == []
    assert client.get("/api/closures", params={"from": "2026-11-09T00:00:00+02:00"}).json() == []


def test_errors_have_contract_shape(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    m.ErrorResponse.model_validate(r.json())
    r = client.get("/api/closures", params={"status": "nope"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_INPUT"
