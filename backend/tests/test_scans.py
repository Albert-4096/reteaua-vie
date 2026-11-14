import pytest
from fastapi.testclient import TestClient

from app.common import state
from app.scans import api_scans


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    try:
        get_settings.cache_clear()
    except AttributeError:
        pass
    from app.main import app

    state.write("closures", "cl_t", {"id": "cl_t"})
    api_scans._recent_all.clear()
    api_scans._recent_stop.clear()
    yield TestClient(app)
    try:
        get_settings.cache_clear()
    except AttributeError:
        pass


def test_post_and_get(client):
    assert client.post("/api/closures/cl_t/scans?stop=434").status_code == 200
    client.post("/api/closures/cl_t/scans?stop=434")
    client.post("/api/closures/cl_t/scans?stop=12")
    j = client.get("/api/closures/cl_t/scans").json()
    assert j["total"] == 3
    assert j["stops"][0]["stopId"] == "434" and j["stops"][0]["count"] == 2
    raw = state.read("scans", "cl_t")
    assert "ip" not in str(raw).lower()


def test_unknown_closure_and_bad_stop(client):
    assert client.post("/api/closures/nope/scans?stop=1").status_code == 404
    assert client.post("/api/closures/cl_t/scans?stop=a b").status_code == 422
    assert client.post("/api/closures/cl_t/scans").status_code == 422


def test_rate_limit(client):
    codes = [client.post("/api/closures/cl_t/scans?stop=1").status_code for _ in range(25)]
    assert codes[:20] == [200] * 20 and codes[20] == 429
    assert client.post("/api/closures/cl_t/scans?stop=2").status_code == 200
