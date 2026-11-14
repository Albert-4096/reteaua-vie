"""SMTT GTFS: the planned timetable and its departure index.

Source: the feed in force at a date, among the zips in $LIVE_DIR/gtfs/ (the
recorder re-downloads the SMTT zip) and $DATA_DIR/smtt-timisoara-ro_2026-11-11.zip:
the highest feed_version whose start (feed_info feed_start_date, else the
earliest calendar date) is on or before the date. The date defaults to the app
clock (DEMO_NOW, or the real time when DEMO_NOW=real). SMTT publishes a feed
before it starts (4.32 on 14 Nov, from 16 Nov), so the newest file is not
always the one in force. GTFS route_id / stop_id are the same ids the city
network serves (R_TV_4, "61"), checked on feed 4.31.

Service days come from calendar.txt + calendar_dates.txt (frequencies.txt is
empty). The departure index has one row per scheduled departure for every
service date the feed covers: (stop, route, direction, service date, time).
Departures only: the last stop of each trip is not a departure. GTFS times
past 24:00 count from 'noon minus 12 h' of the service day, so they roll into
the next calendar day. The index is cached as Parquet in $DATA_DIR/cache,
keyed by the feed's sha256.

Public API (used by M1 and later modules):
    feed_path(at=None) -> Path          the zip in force at `at` (default: the app clock)
    feed(at=None) -> Feed               tables + version + hash + provenance
    service_ids_on(day) -> set[str]
    stop_order(route_id, direction_id) -> list[str]
    stop_patterns() -> dict[(route, dir), Pattern]
    departure_index() -> DataFrame      sorted by dep_ts
    departures(start, end, stop_ids=, route_ids=, direction_id=, keys=) -> DataFrame
    count_departures(start, end, ...) -> int
    count_by_key(start, end, keys=...) -> dict[(stop, route, dir), int]
    minute_counts(start, end, ...) -> numpy array (one bin per minute)
    coverage() -> (first, last) service date of the feed
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from app.common import provenance as prov
from app.common.errors import unavailable
from app.common.timeutil import file_mtime, gtfs_service_start
from app.config import TZ, get_settings, now
from app.models.base import Provenance

FALLBACK_ZIP = "smtt-timisoara-ro_2026-11-11.zip"
INDEX_VERSION = 1  # bump when the index columns change

Key = tuple[str, str, int]  # (stop_id, route_id, direction_id)


# --- feed location ---------------------------------------------------------------


def _version_key(version: str | None) -> tuple[int, ...]:
    """'4.31' -> (4, 31), '4.31.1' -> (4, 31, 1); no version sorts first."""
    return tuple(int(n) for n in re.findall(r"\d+", version or ""))


@lru_cache(maxsize=64)
def _zip_meta(path_str: str, mtime: float, size: int) -> tuple[str | None, date | None]:
    """(feed_version, first service date) from feed_info.txt, else the earliest calendar date."""
    def rows(z: zipfile.ZipFile, name: str) -> list[dict]:
        if name not in z.namelist():
            return []
        return list(csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig")))

    try:
        with zipfile.ZipFile(path_str) as z:
            info = rows(z, "feed_info.txt")
            version = (info[0].get("feed_version") or None) if info else None
            start = (info[0].get("feed_start_date") or "").strip() if info else ""
            if not start:
                days = [r.get("start_date", "") for r in rows(z, "calendar.txt")]
                days += [r.get("date", "") for r in rows(z, "calendar_dates.txt")]
                days = sorted(d for d in days if d)
                start = days[0] if days else ""
    except (OSError, zipfile.BadZipFile, ValueError):
        return None, None
    return version, (_ymd(start) if start else None)


def _candidates() -> list[Path]:
    s = get_settings()
    live = s.live_dir / "gtfs"
    zips = list(live.glob("*.zip")) if live.is_dir() else []
    fb = s.data_dir / FALLBACK_ZIP
    if fb.is_file():
        zips.append(fb)
    return zips


def _day(at: datetime | date | None) -> date:
    if at is None:
        at = now()
    return at.astimezone(TZ).date() if isinstance(at, datetime) else at


def feed_path(at: datetime | date | None = None) -> Path | None:
    """The GTFS zip in force at `at` (default: the app clock, DEMO_NOW or real time).

    Among the candidates whose first service date is on or before that day,
    the highest feed_version (ties: the newest file). If every feed starts
    later, the one that starts first.
    """
    day = _day(at)
    metas = []
    for p in _candidates():
        st = p.stat()
        version, start = _zip_meta(str(p), st.st_mtime, st.st_size)
        metas.append((p, version, start, st.st_mtime))
    if not metas:
        return None
    started = [m for m in metas if m[2] is None or m[2] <= day]
    if started:
        return max(started, key=lambda m: (_version_key(m[1]), m[3]))[0]
    return min(metas, key=lambda m: (m[2], [-n for n in _version_key(m[1])]))[0]


def feed_file_time(at: datetime | date | None = None) -> datetime | None:
    p = feed_path(at)
    return file_mtime(p) if p else None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --- feed tables -------------------------------------------------------------------


def _hms_to_sec(col: pd.Series) -> np.ndarray:
    parts = col.str.split(":", expand=True).astype(int)
    return (parts[0] * 3600 + parts[1] * 60 + parts[2]).to_numpy(dtype=np.int32)


def _ymd(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


@dataclass(frozen=True)
class Feed:
    path: Path
    sha256: str
    version: str | None
    start: date | None          # feed_info feed_start_date
    end: date | None            # feed_info feed_end_date
    routes: pd.DataFrame
    stops: pd.DataFrame
    trips: pd.DataFrame
    stop_times: pd.DataFrame    # + dep_sec, arr_sec (int, may exceed 86400)
    calendar: pd.DataFrame
    calendar_dates: pd.DataFrame

    @property
    def provenance(self) -> Provenance:
        return prov.gtfs_provenance(self.path, self.version, self.sha256)


def _read(z: zipfile.ZipFile, name: str) -> pd.DataFrame:
    if name not in z.namelist():
        return pd.DataFrame()
    raw = z.read(name).decode("utf-8-sig")
    return pd.read_csv(io.StringIO(raw), dtype=str, keep_default_na=False)


@lru_cache(maxsize=2)
def _load_feed(path_str: str, mtime: float) -> Feed:
    path = Path(path_str)
    with zipfile.ZipFile(path) as z:
        t = {n: _read(z, f"{n}.txt") for n in
             ("routes", "stops", "trips", "stop_times", "calendar", "calendar_dates", "feed_info")}
    st = t["stop_times"]
    st["dep_sec"] = _hms_to_sec(st["departure_time"])
    st["arr_sec"] = _hms_to_sec(st["arrival_time"])
    st["stop_sequence"] = st["stop_sequence"].astype(int)
    trips = t["trips"]
    trips["direction_id"] = trips["direction_id"].replace("", "0").astype(int)
    info = t["feed_info"]
    version = info["feed_version"].iloc[0] if len(info) and "feed_version" in info else None
    start = _ymd(info["feed_start_date"].iloc[0]) if len(info) and info["feed_start_date"].iloc[0] else None
    end = _ymd(info["feed_end_date"].iloc[0]) if len(info) and info["feed_end_date"].iloc[0] else None
    return Feed(path=path, sha256=_sha256(path), version=version, start=start, end=end,
                routes=t["routes"], stops=t["stops"], trips=trips, stop_times=st,
                calendar=t["calendar"], calendar_dates=t["calendar_dates"])


# sha256 -> Feed, so the caches keyed by sha below read the feed they were asked for
_FEEDS: dict[str, Feed] = {}


def feed(at: datetime | date | None = None) -> Feed:
    """The feed in force at `at` (default: the app clock); see feed_path()."""
    p = feed_path(at)
    if p is None:
        raise unavailable("No GTFS feed in DATA_DIR (run `make data`).")
    f = _load_feed(str(p), p.stat().st_mtime)
    _FEEDS[f.sha256] = f
    return f


# --- service calendar ----------------------------------------------------------------

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@lru_cache(maxsize=4)
def _service_dates(sha: str) -> dict[date, frozenset[str]]:
    f = _FEEDS[sha]
    by_day: dict[date, set[str]] = {}
    for row in f.calendar.itertuples(index=False):
        d, end = _ymd(row.start_date), _ymd(row.end_date)
        flags = [getattr(row, w) == "1" for w in _WEEKDAYS]
        while d <= end:
            if flags[d.weekday()]:
                by_day.setdefault(d, set()).add(row.service_id)
            d += timedelta(days=1)
    for row in f.calendar_dates.itertuples(index=False):
        d = _ymd(row.date)
        if row.exception_type == "1":
            by_day.setdefault(d, set()).add(row.service_id)
        elif row.exception_type == "2":
            by_day.setdefault(d, set()).discard(row.service_id)
    return {d: frozenset(s) for d, s in by_day.items()}


def service_ids_on(day: date) -> frozenset[str]:
    """Service ids running on a service date (calendar + calendar_dates)."""
    return _service_dates(feed().sha256).get(day, frozenset())


def coverage() -> tuple[date, date]:
    """First and last service date with any service. Outside it: unknown, not zero."""
    days = sorted(d for d, s in _service_dates(feed().sha256).items() if s)
    return days[0], days[-1]


# --- stop order per (route, direction) -----------------------------------------------


@dataclass(frozen=True)
class Pattern:
    route_id: str
    direction_id: int
    stop_ids: tuple[str, ...]   # in travel order
    headsign: str
    trips: int                  # trips with exactly this pattern
    share: float                # of all trips of the route + direction


@lru_cache(maxsize=4)
def _patterns(sha: str) -> dict[tuple[str, int], Pattern]:
    f = _FEEDS[sha]
    st = f.stop_times.sort_values(["trip_id", "stop_sequence"])
    seqs = st.groupby("trip_id", sort=False)["stop_id"].agg(tuple)
    trips = f.trips.set_index("trip_id")
    out: dict[tuple[str, int], Pattern] = {}
    for (route, direction), grp in trips.groupby(["route_id", "direction_id"]):
        counts = Counter(seqs.get(t) for t in grp.index if t in seqs.index)
        if not counts:
            continue
        stop_ids, n = counts.most_common(1)[0]
        heads = grp.loc[[t for t in grp.index if seqs.get(t) == stop_ids], "trip_headsign"]
        out[(route, int(direction))] = Pattern(
            route_id=route, direction_id=int(direction), stop_ids=stop_ids,
            headsign=heads.mode().iloc[0] if len(heads) else "",
            trips=n, share=n / sum(counts.values()),
        )
    return out


def stop_patterns() -> dict[tuple[str, int], Pattern]:
    """Most common trip pattern per (route_id, direction_id)."""
    return _patterns(feed().sha256)


def stop_order(route_id: str, direction_id: int) -> list[str]:
    p = stop_patterns().get((route_id, int(direction_id)))
    return list(p.stop_ids) if p else []


# --- departure index ---------------------------------------------------------------


def _index_path(sha: str) -> Path:
    return get_settings().cache_dir / f"gtfs_departures_v{INDEX_VERSION}_{sha[:16]}.parquet"


def _build_index(f: Feed) -> pd.DataFrame:
    st = f.stop_times
    # departures only: drop the last stop of each trip
    last = st.groupby("trip_id")["stop_sequence"].transform("max")
    dep = st[st["stop_sequence"] < last][["trip_id", "stop_id", "stop_sequence", "dep_sec"]]
    dep = dep.merge(f.trips[["trip_id", "route_id", "direction_id", "service_id"]], on="trip_id")
    by_service = {sid: g for sid, g in dep.groupby("service_id")}
    frames = []
    for day, services in sorted(_service_dates(f.sha256).items()):
        base = int(gtfs_service_start(day).astimezone(timezone.utc).timestamp())
        ymd = day.year * 10000 + day.month * 100 + day.day
        for sid in services:
            g = by_service.get(sid)
            if g is None:
                continue
            frames.append(pd.DataFrame({
                "dep_ts": base + g["dep_sec"].to_numpy(dtype=np.int64),
                "service_date": np.int32(ymd),
                "stop_id": g["stop_id"].to_numpy(),
                "route_id": g["route_id"].to_numpy(),
                "direction_id": g["direction_id"].to_numpy(dtype=np.int8),
                "trip_id": g["trip_id"].to_numpy(),
                "stop_sequence": g["stop_sequence"].to_numpy(dtype=np.int16),
            }))
    idx = pd.concat(frames, ignore_index=True)
    for c in ("stop_id", "route_id", "trip_id"):
        idx[c] = idx[c].astype("category")
    return idx.sort_values("dep_ts", kind="stable").reset_index(drop=True)


@lru_cache(maxsize=2)
def _index(sha: str) -> pd.DataFrame:
    path = _index_path(sha)
    if path.is_file():
        return pd.read_parquet(path)
    idx = _build_index(_FEEDS[sha])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    idx.to_parquet(tmp, index=False)
    tmp.replace(path)
    return idx


def departure_index() -> pd.DataFrame:
    """All scheduled departures of the feed, sorted by dep_ts (unix seconds).

    Columns: dep_ts, service_date (YYYYMMDD int), stop_id, route_id,
    direction_id, trip_id, stop_sequence.
    """
    return _index(feed().sha256)


def _ts(dt: datetime) -> int:
    if dt.tzinfo is None:
        raise ValueError("naive datetime: give an offset (Europe/Bucharest)")
    return int(dt.timestamp())


def departures(start: datetime, end: datetime, *, stop_ids: Iterable[str] | None = None,
               route_ids: Iterable[str] | None = None, direction_id: int | None = None,
               keys: Iterable[Key] | None = None) -> pd.DataFrame:
    """Scheduled departures with start <= time < end, filtered.

    `keys` = exact (stop_id, route_id, direction_id) triples; the other filters
    combine with AND.
    """
    idx = departure_index()
    ts = idx["dep_ts"].to_numpy()
    lo, hi = np.searchsorted(ts, _ts(start), "left"), np.searchsorted(ts, _ts(end), "left")
    df = idx.iloc[lo:hi]
    if stop_ids is not None:
        df = df[df["stop_id"].isin(list(stop_ids))]
    if route_ids is not None:
        df = df[df["route_id"].isin(list(route_ids))]
    if direction_id is not None:
        df = df[df["direction_id"] == int(direction_id)]
    if keys is not None:
        keys = list(keys)
        if not keys:
            return df.iloc[0:0]
        k = pd.MultiIndex.from_tuples([(s, r, int(d)) for s, r, d in keys])
        mi = pd.MultiIndex.from_arrays([df["stop_id"].astype(str), df["route_id"].astype(str),
                                        df["direction_id"].astype(int)])
        df = df[mi.isin(k)]
    return df


def count_departures(start: datetime, end: datetime, **filters) -> int:
    return int(len(departures(start, end, **filters)))


def count_by_key(start: datetime, end: datetime, **filters) -> dict[Key, int]:
    """{(stop_id, route_id, direction_id): departures in [start, end)}."""
    df = departures(start, end, **filters)
    if df.empty:
        return {}
    g = df.groupby([df["stop_id"].astype(str), df["route_id"].astype(str),
                    df["direction_id"].astype(int)]).size()
    return {(s, r, int(d)): int(n) for (s, r, d), n in g.items()}


def minute_counts(start: datetime, end: datetime, **filters) -> np.ndarray:
    """Departures per minute in [start, end): array[i] = minute start + i.

    For window ranking: a window of h hours starting at minute i loses
    cumsum[i + 60h] - cumsum[i] departures.
    """
    df = departures(start, end, **filters)
    n = max(0, -(-(_ts(end) - _ts(start)) // 60))
    if df.empty:
        return np.zeros(n, dtype=np.int32)
    bins = (df["dep_ts"].to_numpy() - _ts(start)) // 60
    return np.bincount(bins, minlength=n)[:n].astype(np.int32)


def is_covered(start: datetime, end: datetime) -> bool:
    """True if every service day touched by [start, end) is inside the feed."""
    first, last = coverage()
    return first <= start.astimezone(TZ).date() and (end - timedelta(seconds=1)).astimezone(TZ).date() <= last
