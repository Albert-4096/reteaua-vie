"""L5: replay frames from our recording (app/live/replay.py, GET /api/live/replay)."""

from __future__ import annotations

import gzip

import pytest

from app.common.timeutil import parse_iso
from app.live import replay
from tests.conftest import DATA_DIR, needs_data

VEH = DATA_DIR / "live" / "vehicles"
needs_sat = pytest.mark.skipif(not all((VEH / f"20261114-{h:02d}.jsonl.gz").is_file() for h in range(4, 9)),
                               reason="no 14 Nov 06:00-11:00 recording")
A, B = "2026-11-14T06:00:00+02:00", "2026-11-14T10:41:00+02:00"


def test_gap_when_no_snapshot_is_fresh(monkeypatch):
    from datetime import datetime, timedelta, timezone
    t0 = datetime(2026, 11, 14, 4, 0, 0, tzinfo=timezone.utc)
    snaps = [{"fetchedAt": (t0 + timedelta(seconds=s)).isoformat(), "vehicles": [
        {"id": "9", "routeId": "R_TV_1", "lat": 45.123456, "lon": 21.5, "bearing": 90, "delaySec": None}]}
        for s in (0, 15, 30, 300, 315)]
    monkeypatch.setattr(replay, "_snapshots", lambda a, b: ([replay.vehicles.snapshot_time(s).timestamp() for s in snaps], snaps))
    r = replay.build(t0, t0 + timedelta(seconds=330), 30)
    fr = {f["t"][11:19]: f for f in r["frames"]}
    assert "gap" not in fr["06:00:00"] and fr["06:00:00"]["vehicles"] == [["9", "R_TV_1", 45.12346, 21.5, 90, None]]
    assert fr["06:01:30"].get("gap") is True and "vehicles" not in fr["06:01:30"]   # 60 s after the last snapshot
    assert r["gapCount"] == sum(1 for f in r["frames"] if f.get("gap")) >= 4
    assert "nu a circulat" not in str(r).replace("nu înseamnă că nu a circulat nimic", "")


@needs_data
@needs_sat
def test_default_window_frames_sources_and_size():
    start, end = parse_iso(A), parse_iso(B)
    r = replay.build(start, end, 60)
    assert r["frameCount"] == 282 and len(r["frames"]) == 282
    # no vehicle absent from the snapshot it comes from
    ts, snaps = replay._snapshots(start, end)
    import bisect
    for fr in r["frames"][::20]:
        if fr.get("gap"):
            continue
        t = parse_iso(fr["t"]).timestamp()
        src = snaps[bisect.bisect_right(ts, t) - 1]
        assert t - ts[bisect.bisect_right(ts, t) - 1] <= replay.MAX_AGE_SEC
        ids = {(str(v["id"]), v["routeId"]) for v in src["vehicles"]}
        assert {(row[0], row[1]) for row in fr["vehicles"]} <= ids
    assert set(r["routes"]) >= {row[1] for fr in r["frames"] for row in fr.get("vehicles", [])}
    assert len(replay.replay_gz(start, end, 60)) <= 2 * 1024 * 1024


@needs_data
@needs_sat
def test_api_validates_and_serves(client):
    assert client.get("/api/live/replay?from=2026-11-14T06:00:00%2B02:00&to=2026-11-14T13:00:00%2B02:00").status_code == 422
    assert client.get(f"/api/live/replay?stepSec=5").status_code == 422
    r = client.get("/api/live/replay?from=2026-11-14T06:00:00%2B02:00&to=2026-11-14T06:10:00%2B02:00")
    assert r.status_code == 200 and r.json()["frameCount"] == 11 and r.json()["label"]["ro"].startswith("Din datele live")
