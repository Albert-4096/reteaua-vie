"""GET /api/layers/{layer}: module layers dispatch lazily; a missing function is 404 NOT_READY."""

from __future__ import annotations

import sys
import types

from fastapi.testclient import TestClient

from app.main import app
from app.overview import api_layers

client = TestClient(app)


def test_unknown_layer():
    r = client.get("/api/layers/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "UNKNOWN_LAYER"


def test_missing_function_is_not_ready(monkeypatch):
    monkeypatch.setitem(api_layers.MODULE_LAYERS, "bike", ("app.m5_bike.no_such_module_xyz", "bike_layer"))
    r = client.get("/api/layers/bike")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_READY"


def test_dispatch_passes_bbox(monkeypatch):
    fake = types.ModuleType("fake_layers")
    seen = {}

    def population_layer(bbox):
        seen["bbox"] = bbox
        return {"type": "FeatureCollection", "features": [], "layer": "population", "provenance": []}

    fake.population_layer = population_layer
    monkeypatch.setitem(sys.modules, "fake_layers", fake)
    monkeypatch.setitem(api_layers.MODULE_LAYERS, "population", ("fake_layers", "population_layer"))
    r = client.get("/api/layers/population", params={"bbox": "21.2,45.7,21.3,45.8"})
    assert r.status_code == 200 and r.json()["layer"] == "population"
    assert seen["bbox"] == (21.2, 45.7, 21.3, 45.8)
    assert client.get("/api/layers/population", params={"bbox": "1,2"}).status_code == 422


def test_parking_still_served():
    r = client.get("/api/layers/parking", params={"bbox": "21.21,45.74,21.23,45.76"})
    assert r.status_code == 200 and r.json()["layer"] == "parking"
