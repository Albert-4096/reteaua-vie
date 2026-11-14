"""Per-source freshness for /api/health `sources[]` (N3-B).

Everything comes from what is on disk: file mtimes, the GTFS feed_version and
the files the recorder wrote under $LIVE_DIR. Nothing is invented. A source we
do not hold is left out of the list. Age is measured against the real clock
(not DEMO_NOW): "stale" is about how old the file is, not about the simulation.

`stale` thresholds (seconds since `lastOkAt`), tied to how often the recorder
writes each source:
    vehicles  300      positions are recorded every few seconds (hourly files)
    sesizari  7200     the recorder writes one snapshot per hour
    events    43200    one snapshot every 6 hours
    stpt      604800   newest post file; the recorder only writes a file when a post is new
                       or changed, so a quiet WordPress is not a failure (7 days)
    gtfs      604800   the in-force SMTT zip; the feed changes rarely (7 days)
    parking   604800   City Hall snapshot, fetched once (7 days)
`stale` is null when `lastOkAt` is null.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from app.common.timeutil import file_mtime, iso

STALE_AFTER_SEC: dict[str, int] = {
    "gtfs": 7 * 86400,
    "vehicles": 300,
    "stpt": 7 * 86400,
    "sesizari": 2 * 3600,
    "parking": 7 * 86400,
    "events": 12 * 3600,
}


def _newest(directory: Path, pattern: str) -> Path | None:
    try:
        files = [p for p in directory.glob(pattern) if p.is_file()]
    except OSError:
        return None
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _row(sid: str, last_ok: datetime | None, version: str | None, now: datetime) -> dict:
    stale: bool | None = None
    if last_ok is not None:
        stale = (now - last_ok).total_seconds() > STALE_AFTER_SEC[sid]
    return {
        "id": sid,
        "lastOkAt": iso(last_ok) if last_ok else None,
        "version": version,
        "stale": stale,
    }


def _stpt_version(p: Path) -> str | None:
    m = re.match(r"^(\d+)_", p.name)
    return m.group(1) if m else None


def build_sources(
    live_dir: Path,
    *,
    gtfs_time: datetime | None,
    gtfs_version: str | None,
    parking_time: datetime | None,
    now: datetime | None = None,
) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    rows: list[dict] = []
    if gtfs_time is not None or gtfs_version is not None:
        rows.append(_row("gtfs", gtfs_time, gtfs_version, now))
    # vehicles: the newest hourly file of the recorder; its mtime is the last write
    v = _newest(live_dir / "vehicles", "*.jsonl.gz")
    if v is not None:
        rows.append(_row("vehicles", file_mtime(v), v.name.removesuffix(".jsonl.gz"), now))
    # stpt.ro posts: newest recorded post file (written only when a post is new/changed)
    s = _newest(live_dir / "stpt-posts", "*.json")
    if s is not None:
        rows.append(_row("stpt", file_mtime(s), _stpt_version(s), now))
    for sid, folder in (("sesizari", "sesizari"), ("events", "events")):
        f = _newest(live_dir / folder, "*.json")
        if f is not None:
            rows.append(_row(sid, file_mtime(f), f.stem, now))
    if parking_time is not None:
        rows.append(_row("parking", parking_time, None, now))
    return rows
