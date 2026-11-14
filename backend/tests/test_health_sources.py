import gzip
import os
import time
from datetime import datetime, timedelta, timezone

from app.overview.sources import build_sources


def _touch(p, age_sec):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"{}")
    t = time.time() - age_sec
    os.utime(p, (t, t))


def test_sources_from_disk(tmp_path):
    now = datetime.now(timezone.utc)
    _touch(tmp_path / "vehicles" / "20261114-09.jsonl.gz", 4000)
    _touch(tmp_path / "vehicles" / "20261114-10.jsonl.gz", 600)
    _touch(tmp_path / "sesizari" / "20261114-0952.json", 600)
    _touch(tmp_path / "events" / "20261113-1152.json", 13 * 3600)
    _touch(tmp_path / "stpt-posts" / "11070_20261110T170322.json", 60)
    rows = {r["id"]: r for r in build_sources(
        tmp_path, gtfs_time=now - timedelta(hours=2), gtfs_version="4.31", parking_time=None, now=now)}
    assert rows["vehicles"]["version"] == "20261114-10" and rows["vehicles"]["stale"] is True
    assert rows["sesizari"]["stale"] is False
    assert rows["events"]["stale"] is True
    assert rows["stpt"]["version"] == "11070"
    assert rows["gtfs"]["version"] == "4.31" and rows["gtfs"]["stale"] is False
    assert "parking" not in rows  # not held: left out


def test_empty_dir_leaves_sources_out(tmp_path):
    assert build_sources(tmp_path, gtfs_time=None, gtfs_version=None, parking_time=None) == []


def test_deployed_sha_from_env(monkeypatch):
    from app.overview.api_overview import health

    monkeypatch.delenv("GIT_SHA", raising=False)
    assert health().deployedSha is None
    monkeypatch.setenv("GIT_SHA", "abc1234")
    assert health().deployedSha == "abc1234"
