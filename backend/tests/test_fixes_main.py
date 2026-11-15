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


def test_frontend_served_with_spa_fallback(tmp_path):
    from fastapi import FastAPI

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "a.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("no")
    app = FastAPI()

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    assert main.mount_frontend(app, dist)
    c = TestClient(app)
    assert c.get("/api/ping").json() == {"ok": True}
    assert c.get("/").text == "<html>app</html>"
    assert c.get("/assets/a.js").text == "console.log(1)"
    assert c.get("/a/cl_x", params={"stop": "85"}).text == "<html>app</html>"
    assert c.get("/api/nope").status_code == 404
    assert "no" != c.get("/../secret.txt").text


def test_v1_routes_get_v1_html(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>v3</html>")
    (dist / "v1.html").write_text("<html>v1</html>")
    c = TestClient(FastAPI())
    main.mount_frontend(c.app, dist)
    assert c.get("/").text == "<html>v3</html>"
    assert c.get("/app/planifici", params={"c": "cl_x"}).text == "<html>v3</html>"
    assert c.get("/a/cl_x", params={"stop": "85"}).text == "<html>v3</html>"  # the QR phone page moved to v3
    assert c.get("/step/3").text == "<html>v1</html>"
    assert c.get("/v1").text == "<html>v1</html>"
    assert c.get("/api/nope").status_code == 404


def test_no_dist_no_mount(tmp_path):
    from fastapi import FastAPI

    assert main.mount_frontend(FastAPI(), tmp_path / "missing") is False
