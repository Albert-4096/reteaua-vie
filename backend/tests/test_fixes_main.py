"""main.py router discovery: a module that fails to import is skipped, the rest stay up."""

from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

import app.main as main


def test_broken_module_is_skipped(monkeypatch):
    real_import = importlib.import_module
    victim = "app.overview.api_layers"

    def fake_import(name, *a, **kw):
        if name == victim:
            raise SyntaxError("broken on purpose")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(main.importlib, "import_module", fake_import)
    routers, failed = main.discover_routers()
    names = [n for n, _ in routers]
    assert failed == [victim]
    assert victim not in names
    assert "app.overview.api_overview" in names


def test_health_lists_failed_modules(monkeypatch):
    client = TestClient(main.app)
    body = client.get("/api/health").json()
    assert body["modulesFailed"] == []
    monkeypatch.setattr(main, "MODULES_FAILED", ["app.mx.api_x"])
    assert client.get("/api/health").json()["modulesFailed"] == ["app.mx.api_x"]
