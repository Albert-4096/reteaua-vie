"""Per-trip facts from the raw vehicle recording that L0 does not keep (the `wheelchair` flag).

One small Parquet per closed recording hour, in $CACHE_DIR/analytics/trips/. A report counts
once per (vehicle, updatedAt). A trip run = (tripId, vehicle, service date); the service date is
the local date of the first report minus 3 h, so a trip that runs past midnight keeps its day.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

from app.common import vehicles
from app.common.timeutil import from_unix
from app.config import TZ, get_settings

log = logging.getLogger("reteaua_vie.analytics")

COLUMNS = ["trip", "vid", "sdate", "route", "dir", "t_first", "t_last", "n_true", "n_false", "n_null"]
SERVICE_DAY_SHIFT_H = 3


def _cache_dir():
    d = get_settings().cache_dir / "analytics" / "trips"
    d.mkdir(parents=True, exist_ok=True)
    return d


def parse_hour(path) -> pd.DataFrame:
    """The reports of one recording file reduced to one row per (trip, vehicle)."""
    rows: dict[tuple, list] = {}
    seen: set[tuple] = set()
    for snap in vehicles._read_lines(path):
        for v in snap.get("vehicles") or []:
            trip, vid, upd = v.get("tripId"), v.get("id"), v.get("updatedAt")
            if not trip or vid is None or upd is None or (vid, upd) in seen:
                continue
            seen.add((vid, upd))
            try:
                t = int(upd)
            except (TypeError, ValueError):
                continue
            sd = (from_unix(t).astimezone(TZ) - timedelta(hours=SERVICE_DAY_SHIFT_H)).strftime("%Y-%m-%d")
            key = (str(trip), str(vid), sd)
            r = rows.get(key)
            if r is None:
                r = rows[key] = [v.get("routeId"), v.get("directionId"), t, t, 0, 0, 0]
            r[2], r[3] = min(r[2], t), max(r[3], t)
            w = v.get("wheelchair")
            r[4 if w is True else 5 if w is False else 6] += 1
    data = [[k[0], k[1], k[2], str(r[0]) if r[0] is not None else None, r[1], *r[2:]] for k, r in rows.items()]
    return pd.DataFrame(data, columns=COLUMNS)


def _hour_table(path, closed: bool) -> pd.DataFrame:
    cache = _cache_dir() / (path.name[: -len(".jsonl.gz")] + ".parquet")
    if closed and cache.is_file():
        return pd.read_parquet(cache)
    df = parse_hour(path)
    if closed:
        try:
            df.to_parquet(cache)
        except OSError:
            log.exception("could not cache %s", cache)
    return df


def trip_runs() -> tuple[pd.DataFrame, datetime | None, datetime | None]:
    """(one row per trip run, first, last recorded snapshot time). Reads the whole recording."""
    files = vehicles.recording_files()
    if not files:
        return pd.DataFrame(columns=COLUMNS), None, None
    parts = [_hour_table(p, closed=i < len(files) - 1) for i, (p, _h) in enumerate(files)]
    parts = [p for p in parts if len(p)]
    span = vehicles.recording_span()
    first, last = span if span else (None, None)
    if not parts:
        return pd.DataFrame(columns=COLUMNS), first, last
    df = pd.concat(parts, ignore_index=True)
    df = df.groupby(["trip", "vid", "sdate"], as_index=False, sort=False).agg(
        route=("route", "first"), dir=("dir", "first"), t_first=("t_first", "min"), t_last=("t_last", "max"),
        n_true=("n_true", "sum"), n_false=("n_false", "sum"), n_null=("n_null", "sum"))
    return df, first, last


def with_local_time(df: pd.DataFrame) -> pd.DataFrame:
    """Adds `hour`: the local hour of the trip's first report."""
    out = df.copy()
    out["hour"] = pd.to_datetime(out["t_first"], unit="s", utc=True).dt.tz_convert(TZ).dt.hour
    return out

