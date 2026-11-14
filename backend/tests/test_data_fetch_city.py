"""The city fetcher and the vehicle recorder (scripts/data/): parsing, the
keep-last-good rule, and the backend reading what they write.

No network: `fetch_city.http_get` is replaced by the hand-made fixtures in
tests/fixtures/city/; the GTFS zips are built here.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import sys
import time
import urllib.error
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "data"))
import fetch_city  # noqa: E402
import record_vehicles  # noqa: E402

from app import config  # noqa: E402
from app.common import city, gtfs, stpt_posts, vehicles  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "city"
CITY_SOURCES = ["gtfs", "network", "zones", "parking", "streets", "stpt", "sesizari"]


def gtfs_zip(version: str) -> bytes:
    files = {
        "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\n1,Test,https://example.invalid,Europe/Bucharest\n",
        "routes.txt": "route_id,route_short_name,route_type\nR_TV_1,1,0\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\n1,A,45.75,21.22\n2,B,45.755,21.225\n",
        "trips.txt": "route_id,service_id,trip_id,direction_id\nR_TV_1,LV,t-1,0\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                          "t-1,08:00:00,08:00:00,1,1\nt-1,08:05:00,08:05:00,2,2\n",
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                        "LV,1,1,1,1,1,0,0,20261101,20261231\n",
        "feed_info.txt": "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date,feed_version\n"
                         f"Test,https://example.invalid,ro,20261101,20261231,{version}\n",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


def ok(body: bytes, etag: str | None = None) -> fetch_city.Response:
    return fetch_city.Response(200, {"etag": f'"{etag}"'} if etag else {}, body)


class FakeHTTP:
    """url prefix -> Response or exception; records every call."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, headers=None, timeout=60):
        self.calls.append((url, dict(headers or {})))
        for prefix, resp in self.routes.items():
            if url.startswith(prefix):
                if isinstance(resp, BaseException):
                    raise resp
                return resp(url, headers or {}) if callable(resp) else resp
        raise urllib.error.URLError("unreachable in tests")


def good_routes(gtfs_version: str = "9.99", etag: str = "abc-1") -> dict:
    return {
        fetch_city.GTFS_URL: ok(gtfs_zip(gtfs_version), etag),
        "https://cont.primariatm.ro/api/mobile/transit/network": ok((FIX / "network.json").read_bytes()),
        "https://cont.primariatm.ro/api/zones": ok((FIX / "zones.geojson").read_bytes()),
        "https://cont.primariatm.ro/api/mobile/parking": ok((FIX / "parking.json").read_bytes()),
        "https://servicii.primariatm.ro/api/nomenclator/strazi": ok((FIX / "strazi.json").read_bytes()),
        fetch_city.STPT_URL: ok((FIX / "stpt-posts.json").read_bytes()),
        fetch_city.SESIZARI_URL: ok((FIX / "sesizari.json").read_bytes()),
    }


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    """A fresh DATA_DIR / LIVE_DIR, and the backend readers pointed at it."""
    data, live = tmp_path / "data", tmp_path / "data" / "live"
    data.mkdir()
    fake = config.Settings(env_file=None, data_dir=data, live_dir=live, demo_now=None, data_freeze=False,
                           public_base_url="http://test")
    for mod in (config, city, gtfs, stpt_posts, vehicles):
        monkeypatch.setattr(mod, "get_settings", lambda: fake)
    city.clear_caches()
    yield data, live
    city.clear_caches()


def run(monkeypatch, dirs, routes, freeze=False, only=CITY_SOURCES):
    fake = FakeHTTP(routes)
    monkeypatch.setattr(fetch_city, "http_get", fake)
    failed = fetch_city.run_once(dirs[0], dirs[1], only, freeze)
    return failed, fake


def records(data: Path) -> dict:
    out = json.loads((data / "provenance" / "sources.json").read_text(encoding="utf-8"))
    return {r["id"]: r for r in out["fetched"]}


def test_fetch_writes_the_files_the_backend_reads(monkeypatch, dirs):
    data, live = dirs
    failed, _ = run(monkeypatch, dirs, good_routes())
    assert failed == []

    net = city.load_network()
    assert (net.feed_version, len(net.routes), len(net.stops), len(net.paths)) == ("9.99-1", 1, 3, 1)
    assert city.load_zones().slugs == ["zona-test"]
    assert len(city.load_parking().features) == 2
    assert (data / fetch_city.CITY_DIR / "nomenclator-strazi.json").read_bytes() == (FIX / "strazi.json").read_bytes()

    assert gtfs.feed_path() == live / "gtfs" / "smtt_abc-1.zip"
    posts = stpt_posts.load_posts()
    assert sorted(posts) == [901, 902]
    assert posts[902].path.name == "902_20261112T093000.json"
    assert "10:00" in posts[902].text

    (poll,) = (live / "sesizari").glob("*.json")
    rows = json.loads(poll.read_text(encoding="utf-8"))
    assert [r["id"] for r in rows] == ["s-1", "s-2"]
    assert all("descriere" not in r and "poze" not in r for r in rows)   # no free text, no photos

    rec = records(data)
    assert rec["city-network"]["version"] == "9.99-1"
    assert rec["city-parking"]["version"] == "test-1"
    assert rec["smtt-gtfs"]["version"] == "9.99"
    assert rec["smtt-gtfs"]["file"] == "live/gtfs/smtt_abc-1.zip"
    assert all(r["note"] is None for r in rec.values())


def test_failed_or_bad_source_keeps_the_last_good_file(monkeypatch, dirs):
    data, live = dirs
    run(monkeypatch, dirs, good_routes())
    target = data / fetch_city.CITY_DIR / "transit-network.json"
    before = {p: (p.read_bytes(), p.stat().st_mtime) for p in data.rglob("*") if p.is_file() and "provenance" not in p.parts}

    empty = json.dumps({"feedVersion": "x", "routes": [], "stops": [], "paths": []}).encode()
    broken = good_routes()
    broken.update({
        "https://cont.primariatm.ro/api/mobile/transit/network": ok(empty),                    # empty network
        "https://cont.primariatm.ro/api/zones": ok(b"<html>502 Bad Gateway</html>"),           # not JSON
        "https://cont.primariatm.ro/api/mobile/parking": urllib.error.URLError("timed out"),   # down
        "https://servicii.primariatm.ro/api/nomenclator/strazi": ok(b'{"strazi": []}'),
        fetch_city.GTFS_URL: ok(b"PK\x03\x04 not a zip", "abc-2"),                             # corrupt zip
        fetch_city.STPT_URL: urllib.error.HTTPError(fetch_city.STPT_URL, 503, "busy", {}, None),
    })
    failed, _ = run(monkeypatch, dirs, broken, only=CITY_SOURCES[:-1])
    assert failed == []
    after = {p: (p.read_bytes(), p.stat().st_mtime) for p in data.rglob("*") if p.is_file() and "provenance" not in p.parts}
    assert after == before
    assert json.loads(target.read_text())["feedVersion"] == "9.99-1"
    rec = records(data)
    for rid in ("city-network", "city-zones", "city-parking", "city-streets", "smtt-gtfs", "stpt-posts"):
        assert rec[rid]["note"] == fetch_city.KEPT, rid


def test_failure_without_an_earlier_file_is_reported(monkeypatch, dirs):
    data, _ = dirs
    routes = good_routes()
    routes["https://cont.primariatm.ro/api/mobile/transit/network"] = urllib.error.URLError("down")
    failed, _ = run(monkeypatch, dirs, routes)
    assert failed == ["network"]
    assert not (data / fetch_city.CITY_DIR / "transit-network.json").exists()


def test_gtfs_conditional_get_and_new_version(monkeypatch, dirs):
    data, live = dirs
    run(monkeypatch, dirs, good_routes(), only=["gtfs"])

    routes = {fetch_city.GTFS_URL: fetch_city.Response(304, {}, b"")}
    _, fake = run(monkeypatch, dirs, routes, only=["gtfs"])
    assert fake.calls[0][1].get("If-None-Match") == '"abc-1"'
    assert [p.name for p in (live / "gtfs").glob("*.zip")] == ["smtt_abc-1.zip"]

    time.sleep(0.01)
    run(monkeypatch, dirs, good_routes("10.00", "abc-2"), only=["gtfs"])
    assert gtfs.feed_path().name == "smtt_abc-2.zip"
    assert records(data)["smtt-gtfs"]["version"] == "10.00"


def test_edited_post_gets_a_new_file(monkeypatch, dirs):
    _, live = dirs
    run(monkeypatch, dirs, good_routes(), only=["stpt"])
    posts = json.loads((FIX / "stpt-posts.json").read_text(encoding="utf-8"))
    posts[0]["modified"] = "2026-11-12T11:00:00"
    posts[0]["title"]["rendered"] = "Linia 1 deviată (test, actualizat)"
    run(monkeypatch, dirs, {fetch_city.STPT_URL: ok(json.dumps(posts).encode())}, only=["stpt"])
    names = sorted(p.name for p in (live / "stpt-posts").glob("*.json"))
    assert names == ["901_20261110T080000.json", "902_20261112T093000.json", "902_20261112T110000.json"]
    assert stpt_posts.load_posts()[902].title.endswith("actualizat)")


def test_freeze_downloads_nothing(monkeypatch, dirs):
    data, _ = dirs
    run(monkeypatch, dirs, good_routes())
    _, fake = run(monkeypatch, dirs, {}, freeze=True)
    assert fake.calls == []
    assert records(data)["city-network"]["version"] == "9.99-1"


def test_recorder_appends_lines_the_backend_reads(monkeypatch, dirs):
    _, live = dirs
    vdir = live / "vehicles"
    vdir.mkdir(parents=True)
    monkeypatch.setattr(fetch_city, "http_get", FakeHTTP({record_vehicles.VEHICLES_URL: ok((FIX / "vehicles.json").read_bytes())}))
    first = record_vehicles.poll_once(vdir)
    record_vehicles.poll_once(vdir)
    files = vehicles.recording_files()
    assert len(files) in (1, 2)   # two files only if the polls straddle an hour
    snaps = [s for p, _ in files for s in vehicles.read_file(p)]
    assert len(snaps) == 2
    assert list(snaps[0]) == ["fetchedAt", "realtimeAgeSec", "refreshInSec", "vehicles"]
    assert snaps[0]["fetchedAt"] == first["fetchedAt"] and first["fetchedAt"].endswith("+00:00")
    layer = vehicles.vehicles_layer("R_TV_1")
    assert [f["properties"]["vehicleId"] for f in layer["features"]] == ["T1", "T2"]


def test_recorder_rejects_a_bad_payload_and_a_busy_dir(tmp_path):
    with pytest.raises((KeyError, ValueError)):
        record_vehicles.snapshot(b'{"error": "x"}', datetime.now(UTC))
    assert record_vehicles.someone_else_writing(tmp_path) is None
    busy = tmp_path / "20261113-22.jsonl.gz"
    busy.write_bytes(gzip.compress(b"{}\n"))
    assert record_vehicles.someone_else_writing(tmp_path) == busy
    old = time.time() - 120
    os.utime(busy, (old, old))
    assert record_vehicles.someone_else_writing(tmp_path) is None
