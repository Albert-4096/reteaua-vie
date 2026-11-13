"""Time helpers. Every app time is Europe/Bucharest with an explicit offset."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.config import TZ


def iso(dt: datetime) -> str:
    """ISO 8601 in Bucharest time, seconds precision, with offset."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ).replace(microsecond=0).isoformat()


def parse_iso(value: str) -> datetime:
    """Parse an ISO time; naive values are taken as Bucharest local time."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def from_unix(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone(TZ)


def file_mtime(path: Path) -> datetime:
    return from_unix(path.stat().st_mtime)


def local_midnight(day: date) -> datetime:
    """Start of a calendar day in Bucharest (DST-safe)."""
    return datetime(day.year, day.month, day.day, tzinfo=TZ)


def gtfs_service_start(day: date) -> datetime:
    """GTFS 'noon minus 12h' reference for a service day.

    GTFS times count from noon minus 12 h, which equals local midnight except
    on DST-change days. Times >= 24:00 roll into the next calendar day.
    """
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=TZ)
    # aware-datetime arithmetic in Python is wall-clock; do it in UTC
    return (noon.astimezone(timezone.utc) - timedelta(hours=12)).astimezone(TZ)


def gtfs_time(day: date, seconds: int) -> datetime:
    """Absolute time of a GTFS time (seconds since 'noon - 12h') on a service day."""
    base = gtfs_service_start(day).astimezone(timezone.utc)
    return (base + timedelta(seconds=int(seconds))).astimezone(TZ)


def parse_gtfs_hms(value: str) -> int:
    """'25:10:00' -> 90600 seconds. GTFS times may pass 24:00."""
    h, m, s = value.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def days_between(start: datetime, end: datetime) -> list[date]:
    """Calendar days (Bucharest) touched by [start, end)."""
    s = start.astimezone(TZ).date()
    e = (end.astimezone(TZ) - timedelta(microseconds=1)).date()
    out = []
    d = s
    while d <= e:
        out.append(d)
        d += timedelta(days=1)
    return out
