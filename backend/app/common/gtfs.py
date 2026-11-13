"""SMTT GTFS: feed location (the departure index follows in this module)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.common.timeutil import file_mtime
from app.config import get_settings

FALLBACK_ZIP = "smtt-timisoara-ro_2026-11-11.zip"


def feed_path() -> Path | None:
    """Newest GTFS zip in $LIVE_DIR/gtfs/, else the fallback zip in $DATA_DIR."""
    s = get_settings()
    live = s.live_dir / "gtfs"
    zips = sorted(live.glob("*.zip"), key=lambda p: p.stat().st_mtime) if live.is_dir() else []
    if zips:
        return zips[-1]
    fb = s.data_dir / FALLBACK_ZIP
    return fb if fb.is_file() else None


def feed_file_time() -> datetime | None:
    p = feed_path()
    return file_mtime(p) if p else None
