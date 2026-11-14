import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.common import state


def _zip(path, version, start, stops, st_rows, extra_routes=()):
    def csv(rows):
        return "\n".join(",".join(r) for r in rows) + "\n"

    routes = [("route_id", "route_short_name")] + [("R1", "1"), ("R2", "2")] + [(r, r) for r in extra_routes]
    files = {
        "feed_info.txt": csv([("feed_version", "feed_start_date", "feed_end_date"), (version, start, "20261231")]),
        "routes.txt": csv(routes),
        "stops.txt": csv([("stop_id", "stop_name", "stop_lat", "stop_lon")] + stops),
        "trips.txt": csv([("trip_id", "route_id", "service_id", "direction_id"), ("t1", "R1", "S", "0"), ("t2", "R2", "S", "0")]),
        "stop_times.txt": csv([("trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence")] + st_rows),
        "calendar.txt": csv([("service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"),
                             ("S", "1", "1", "1", "1", "1", "1", "1", start, "20261231")]),
        "calendar_dates.txt": csv([("service_id", "date", "exception_type")]),
    }
    with zipfile.ZipFile(path, "w") as z:
        for n, c in files.items():
            z.writestr(n, c)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    gz = tmp_path / "live" / "gtfs"
    gz.mkdir(parents=True)
    s = lambda i, n, lat="45.75": (i, n, lat, "21.22")
    a_stops = [s("1", "Alfa"), s("2", "Beta"), s("3", "Gama")]
    _zip(gz / "a.zip", "9.1", "20261101", a_stops,
         [("t1", "08:00:00", "08:00:00", "1", "1"), ("t1", "08:05:00", "08:05:00", "2", "2"),
          ("t2", "09:00:00", "09:00:00", "3", "1"), ("t2", "09:05:00", "09:05:00", "1", "2")])
    # target: stop 2 removed, stop 3 renamed, stop 1 unchanged
    b_stops = [s("1", "Alfa"), s("3", "Gama noua")]
    _zip(gz / "b.zip", "9.2", "20261116", b_stops,
         [("t1", "08:00:00", "08:00:00", "1", "1"),
          ("t2", "09:00:00", "09:00:00", "3", "1"), ("t2", "09:05:00", "09:05:00", "1", "2")])
    ents = lambda *x: [{"routeId": r, "stopId": st, "directionId": 0} for r, st in x]
    pub = {"closureId": "c_ok", "alerts": [{"informedEntity": ents(("R2", "1")), "activePeriod": [{"start": "2026-11-01T00:00:00+02:00", "end": "2026-12-31T00:00:00+02:00"}]}]}
    bad = {"closureId": "c_bad", "alerts": [{"informedEntity": ents(("R1", "2"), ("R2", "3")), "activePeriod": [{"start": "2026-11-01T00:00:00+02:00", "end": "2026-12-31T00:00:00+02:00"}]}]}
    old = {"closureId": "c_old", "alerts": [{"informedEntity": ents(("R1", "2")), "activePeriod": [{"start": "2026-11-01T00:00:00+02:00", "end": "2026-11-10T00:00:00+02:00"}]}]}
    for cid, p in (("c_ok", pub), ("c_bad", bad), ("c_old", old)):
        state.write("closures", cid, {"id": cid, "window": {"start": "2026-11-01T00:00:00+02:00", "end": "2026-12-31T00:00:00+02:00"}})
        state.write("published", cid, p)
    from app.main import app

    yield TestClient(app)
    get_settings.cache_clear()


def test_diff(client):
    j = client.get("/api/feed-diff?from=9.1&to=9.2").json()
    assert j["base"]["stops"] == 3 and j["target"]["stops"] == 2
    assert [s["stopId"] for s in j["stopsRemoved"]] == ["2"]
    assert j["tripsAdded"] == 0 and j["tripsRemoved"] == 0
    assert j["tripsChanged"] == 1 and j["patternsRemoved"] == 1
    assert len(j["provenance"]) == 2


def test_check_valid_and_republish_and_not_applicable(client):
    # the base is the feed in force at the app clock (DEMO_NOW 8 Nov): 9.1
    ok = client.get("/api/closures/c_ok/feed-check?version=9.2").json()
    assert ok["base"]["version"] == "9.1" and ok["verdict"] == "valid"
    j = client.get("/api/closures/c_bad/feed-check").json()  # default target: the next version
    assert j["target"]["version"] == "9.2"
    st = {(r["routeId"], r["stopId"]): r["status"] for r in j["rows"]}
    assert st[("R1", "2")] == "stop_missing"
    assert st[("R2", "3")] == "renamed"
    assert j["verdict"] == "republish" and "de verificat" in j["summary"]["ro"]
    assert j["takesEffectOn"] == "2026-11-16"
    assert client.get("/api/closures/c_old/feed-check?version=9.2").json()["verdict"] == "not_applicable"


def test_unknown_version(client):
    r = client.get("/api/feed-diff?from=9.1&to=0.0")
    assert r.status_code == 404 and r.json()["error"]["code"] == "FEED_VERSION_UNKNOWN"
