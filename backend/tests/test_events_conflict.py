import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.common import state


def ts(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LIVE_DIR", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    ev = tmp_path / "live" / "events"
    ev.mkdir(parents=True)
    base = {"type": "event", "category": "x"}
    events = [
        {**base, "id": "near", "title": "Near day event", "venue": "V", "venueLat": 45.7455, "venueLng": 21.2155,
         "dateStart": ts(2026, 11, 10), "dateEnd": ts(2026, 11, 11)},
        {**base, "id": "far", "title": "Far", "venue": "V", "venueLat": 45.80, "venueLng": 21.30,
         "dateStart": ts(2026, 11, 10), "dateEnd": ts(2026, 11, 11)},
        {**base, "id": "novenue", "title": "No venue", "venue": None, "venueLat": None, "venueLng": None,
         "dateStart": ts(2026, 11, 10), "dateEnd": ts(2026, 11, 11)},
        {**base, "id": "later", "title": "After the window", "venue": "V", "venueLat": 45.7455, "venueLng": 21.2155,
         "dateStart": ts(2026, 12, 20), "dateEnd": ts(2026, 12, 21)},
        {**base, "id": "expo", "title": "Long exhibition", "venue": "V", "venueLat": 45.7455, "venueLng": 21.2155,
         "dateStart": ts(2026, 9, 1), "dateEnd": ts(2027, 1, 1)},
    ]
    (ev / "20261113-1152.json").write_text(json.dumps({"events": events}))
    state.write("closures", "cl_x", {"id": "cl_x", "title": {"ro": "t"}, "bufferMeters": 30,
                                       "window": {"start": "2026-11-09T00:00:00+02:00", "end": "2026-11-15T00:00:00+02:00"}})
    from app.main import app

    yield TestClient(app)
    get_settings.cache_clear()


def test_events_listed_by_window_and_distance(client):
    j = client.get("/api/closures/cl_x/events").json()
    assert j["inWindow"] == 4 and j["withoutVenue"] == 1  # far counts in the window, "later" does not
    ids = [e["id"] for e in j["events"]]
    assert ids == []  # no geometry and no lost stops: nothing can be near, and we do not guess


def test_nearest_stop(client):
    state.write("closures", "cl_x", {"id": "cl_x", "title": {"ro": "t"}, "bufferMeters": 30,
                                       "window": {"start": "2026-11-09T00:00:00+02:00", "end": "2026-11-15T00:00:00+02:00"}})
    state.write("closures", "cl_x", {"stops": [{"stopId": "s1", "name": "Stop 1", "location": [21.2150, 45.7454],
                                                 "state": "affected", "confirmed": True, "routeId": "R1",
                                                 "departuresLost": 5}]}, part="analysis")
    j = client.get("/api/closures/cl_x/events").json()
    by = {e["id"]: e for e in j["events"]}
    assert set(by) == {"near", "expo"}
    assert by["near"]["nearest"]["kind"] == "stop" and by["near"]["nearest"]["meters"] < 100
    assert by["expo"]["ongoing"] is True and by["near"]["ongoing"] is False
    assert [e["id"] for e in j["events"]] == ["near", "expo"]  # day events first


def test_unknown_closure(client):
    assert client.get("/api/closures/nope/events").status_code == 404
