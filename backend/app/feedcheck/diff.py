"""Diff of two GTFS versions already on disk (R21). Nothing is fetched.

Zips are looked up in $LIVE_DIR/gtfs/, $DATA_DIR/gtfs-history/ and the fallback
zip in $DATA_DIR (the same places gtfs.py reads, plus the history folder). When a
version exists twice, the newest file wins.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.common import gtfs
from app.common.errors import ApiError
from app.config import get_settings
from app.feedcheck.models import (
    FeedDiff,
    FeedVersionInfo,
    RouteRef,
    RouteTripDelta,
    ServiceDayDelta,
    StopRef,
)

CAP = 200  # longest list returned for stops / routes


def available() -> dict[str, Path]:
    """feed_version -> zip, over every zip we hold."""
    s = get_settings()
    paths = list(gtfs._candidates())
    hist = s.data_dir / "gtfs-history"
    if hist.is_dir():
        paths += list(hist.glob("*.zip"))
    out: dict[str, Path] = {}
    for p in paths:
        st = p.stat()
        version, _ = gtfs._zip_meta(str(p), st.st_mtime, st.st_size)
        if version and (version not in out or st.st_mtime > out[version].stat().st_mtime):
            out[version] = p
    return out


def unknown_version(version: str) -> ApiError:
    have = ", ".join(sorted(available(), key=gtfs._version_key))
    return ApiError(404, "FEED_VERSION_UNKNOWN", f"No GTFS version {version!r} on disk (have: {have}).")


def load(version: str) -> gtfs.Feed:
    p = available().get(version)
    if p is None:
        raise unknown_version(version)
    f = gtfs._load_feed(str(p), p.stat().st_mtime)
    gtfs._FEEDS[f.sha256] = f
    return f


def default_pair(at=None) -> tuple[str, str]:
    """(version in force at `at`, the next newer version on disk); target falls back to base."""
    have = available()
    cur = gtfs.feed_version(at)
    newer = sorted((v for v in have if gtfs._version_key(v) > gtfs._version_key(cur)), key=gtfs._version_key)
    return cur, (newer[0] if newer else cur)


def info(f: gtfs.Feed) -> FeedVersionInfo:
    return FeedVersionInfo(
        version=f.version,
        startDate=f.start.isoformat() if f.start else None,
        endDate=f.end.isoformat() if f.end else None,
        stops=len(f.stops),
        trips=len(f.trips),
        routes=len(f.routes),
    )


@lru_cache(maxsize=8)
def _patterns(sha: str) -> pd.Series:
    """Departures-or-visits per (route, direction, stop): the number of trips that call there."""
    f = gtfs._FEEDS[sha]
    m = f.stop_times[["trip_id", "stop_id"]].merge(
        f.trips[["trip_id", "route_id", "direction_id"]], on="trip_id", how="inner"
    )
    return m.groupby(["route_id", "direction_id", "stop_id"]).size()


def patterns(f: gtfs.Feed) -> pd.Series:
    gtfs._FEEDS[f.sha256] = f
    return _patterns(f.sha256)


def _service_trip_counts(f: gtfs.Feed) -> dict[date, int]:
    per_service = f.trips.groupby("service_id").size().to_dict()
    gtfs._FEEDS[f.sha256] = f
    return {d: sum(per_service.get(s, 0) for s in sids) for d, sids in gtfs._service_dates(f.sha256).items()}


def _trips_changed(a: gtfs.Feed, b: gtfs.Feed) -> int:
    k = ["trip_id", "stop_id", "arrival_time", "departure_time"]
    both = set(a.trips.trip_id) & set(b.trips.trip_id)
    sa = a.stop_times[a.stop_times.trip_id.isin(both)][k]
    sb = b.stop_times[b.stop_times.trip_id.isin(both)][k]
    m = sa.merge(sb, how="outer", indicator=True)
    return int(m.loc[m["_merge"] != "both", "trip_id"].nunique())


def _stops(f: gtfs.Feed, ids: set[str]) -> list[StopRef]:
    names = dict(zip(f.stops.stop_id, f.stops.stop_name))
    return [StopRef(stopId=i, name=names.get(i, "")) for i in sorted(ids, key=lambda x: (len(x), x))][:CAP]


def _routes(f: gtfs.Feed, ids: set[str]) -> list[RouteRef]:
    short = dict(zip(f.routes.route_id, f.routes.route_short_name))
    return [RouteRef(routeId=i, shortName=short.get(i, "")) for i in sorted(ids)][:CAP]


def diff_feeds(a: gtfs.Feed, b: gtfs.Feed) -> FeedDiff:
    sa, sb = set(a.stops.stop_id), set(b.stops.stop_id)
    ra, rb = set(a.routes.route_id), set(b.routes.route_id)
    ta, tb = set(a.trips.trip_id), set(b.trips.trip_id)
    route_of = {**dict(zip(a.trips.trip_id, a.trips.route_id)), **dict(zip(b.trips.trip_id, b.trips.route_id))}
    short = {**dict(zip(a.routes.route_id, a.routes.route_short_name)),
             **dict(zip(b.routes.route_id, b.routes.route_short_name))}
    delta: dict[str, list[int]] = {}
    for t in tb - ta:
        delta.setdefault(route_of[t], [0, 0])[0] += 1
    for t in ta - tb:
        delta.setdefault(route_of[t], [0, 0])[1] += 1
    by_route = [RouteTripDelta(routeId=r, shortName=short.get(r, ""), added=v[0], removed=v[1])
                for r, v in sorted(delta.items())]
    pa, pb = set(patterns(a).index), set(patterns(b).index)
    ca, cb = _service_trip_counts(a), _service_trip_counts(b)
    both = sorted(d for d in set(ca) & set(cb))
    days = [ServiceDayDelta(date=d.isoformat(), tripsBase=ca[d], tripsTarget=cb[d]) for d in both if ca[d] != cb[d]]
    return FeedDiff(
        base=info(a),
        target=info(b),
        stopsAdded=_stops(b, sb - sa),
        stopsRemoved=_stops(a, sa - sb),
        routesAdded=_routes(b, rb - ra),
        routesRemoved=_routes(a, ra - rb),
        tripsAdded=len(tb - ta),
        tripsRemoved=len(ta - tb),
        tripsByRoute=by_route,
        tripsChanged=_trips_changed(a, b),
        patternsAdded=len(pb - pa),
        patternsRemoved=len(pa - pb),
        serviceDays=days,
        daysCompared=len(both),
        provenance=[a.provenance, b.provenance],
    )


@lru_cache(maxsize=4)
def _diff_cached(sha_a: str, sha_b: str) -> FeedDiff:
    return diff_feeds(gtfs._FEEDS[sha_a], gtfs._FEEDS[sha_b])


def diff_versions(base: str, target: str) -> FeedDiff:
    a, b = load(base), load(target)
    return _diff_cached(a.sha256, b.sha256)
