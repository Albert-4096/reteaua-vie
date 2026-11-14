"""R26 + R19: the recorded sesizări (live/reports.py) joined with the zones, stops and GTFS.

Counts and ages only. A report's text, photos, name and exact point never leave this module.
The recording polls the last 2 days only, so a report's status is the one at the last poll
that still held it; „open” can therefore be higher than today's truth, and the age of the
oldest open report is bounded by when our recording started. The wording says so.
"""

from __future__ import annotations

import io
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely import STRtree
from shapely.geometry import LineString, Point
from shapely.ops import substring

from app.city_reports.models import AreaReports, AreaRow, RoadIssues, RoadSegment
from app.common import gtfs
from app.common import provenance as prov
from app.common.city import load_zones
from app.common.errors import invalid
from app.common.geo import project_lonlats, to_metric, to_wgs84
from app.common.timeutil import iso, local_midnight
from app.config import TZ, now
from app.live import reports as rp
from app.models.base import I18n, Window

MOBILITY = ("Transport în comun", "Trafic rutier și semne de circulație", "Străzi și trotuare")
CLOSED = frozenset({"Finalizata", "Declinata competenta"})
POTHOLE = "Groapă"
SAME_PROBLEM_M = 25.0
STOP_RADIUS_M = 50
MATCH_M = 15
LABEL = I18n(ro="sesizări înregistrate de noi, ultimele 2 zile", en="reports recorded by us, last 2 days")
NOTE = I18n(
    ro=("Doar numere și vârste, fără text, nume sau fotografii. Starea este cea de la ultima înregistrare a sesizării "
        "(interogăm doar ultimele 2 zile), deci „deschise” poate fi mai mare decât în realitate; vârsta cea mai mare este "
        "limitată de începutul înregistrării noastre. Nu spune ce a rezolvat sau nu Primăria."),
    en=("Counts and ages only, no text, names or photos. Status is as of the last poll that held the report (we ask for the "
        "last 2 days only), so „open” may overstate; the oldest age is bounded by when our recording started."))


def categories_for(category: str | None) -> tuple[str, ...]:
    if category in (None, "", "all"):
        return MOBILITY
    if category not in MOBILITY:
        raise invalid(f"`category` must be one of: all, {', '.join(MOBILITY)}.")
    return (category,)


def working_day() -> date:
    """A typical working day inside the feed: the next Wednesday on or after the app date."""
    first, last = gtfs.coverage()
    d = max(now().astimezone(TZ).date(), first)
    d += timedelta(days=(2 - d.weekday()) % 7)
    if d > last:
        d = last - timedelta(days=(last.weekday() - 2) % 7)
    return d


@lru_cache(maxsize=4)
def _departures_by_stop(sha: str, day: date) -> dict[str, int]:
    start = local_midnight(day)
    out: dict[str, int] = defaultdict(int)
    for (stop, _r, _d), n in gtfs.count_by_key(start, start + timedelta(days=1)).items():
        out[stop] += n
    return dict(out)


def _departures() -> tuple[dict[str, int], date]:
    f = gtfs.feed()
    day = working_day()
    return _departures_by_stop(f.sha256, day), day


def _recorded_window() -> Window:
    cov = rp.coverage()
    if cov is None:
        t = now()
        return Window(start=iso(t), end=iso(t))
    return Window(start=iso(cov[0]), end=iso(cov[1]))


def _provenance() -> list:
    files = rp._poll_files()
    fetched = files[-1][1] if files else datetime.now(timezone.utc)
    return [prov.provenance("Primăria Timișoara, sesizări publice (înregistrarea noastră) / public reports, our recording",
                            fetched, rp.SESIZARI_URL, None, "doar numărate; fără text, nume, fotografii sau puncte"),
            gtfs.feed().provenance]


def _distinct(items: list[rp.Report]) -> int:
    """Reports of the same category within 25 m (chained) count as one problem."""
    by_cat: dict[str, list[rp.Report]] = defaultdict(list)
    for r in items:
        by_cat[r.category].append(r)
    total = 0
    for rs in by_cat.values():
        if len(rs) == 1:
            total += 1
            continue
        pts = np.array([[r.x, r.y] for r in rs])
        parent = list(range(len(rs)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i, j in cKDTree(pts).query_pairs(SAME_PROBLEM_M):
            parent[find(i)] = find(j)
        total += len({find(i) for i in range(len(rs))})
    return total


def _row(id_: str, name: str, items: list[rp.Report], dep: int, location=None) -> AreaRow:
    open_ = [r for r in items if r.status not in CLOSED]
    resolved = sum(1 for r in items if r.status in rp.RESOLVED)
    return AreaRow(id=id_, name=name, total=len(items), open=len(open_), resolved=resolved,
                   resolvedShare=round(resolved / len(items), 3) if items else None,
                   oldestOpenAt=iso(min(r.created for r in open_).astimezone(TZ)) if open_ else None,
                   distinctProblems=_distinct(items), departuresPerDay=dep, location=location)


def _selected(cats: tuple[str, ...]) -> list[rp.Report]:
    return [r for r in rp.load_reports().values() if r.category in cats]


def _rank(rows: list[AreaRow]) -> list[AreaRow]:
    return sorted(rows, key=lambda r: (-r.open, -r.departuresPerDay, r.id))


def by_zone(category: str | None) -> AreaReports:
    cats = categories_for(category)
    reps = _selected(cats)
    zones = load_zones()
    metric = [to_metric(s) for s in zones.shapes]
    tree = STRtree(metric)
    members: dict[int, list[rp.Report]] = defaultdict(list)
    for r in reps:
        hit = [i for i in tree.query(Point(r.x, r.y), predicate="within")]
        if hit:
            members[int(hit[0])].append(r)
    f = gtfs.feed()
    deps, day = _departures()
    stops_xy = project_lonlats(zip(f.stops.stop_lon.astype(float), f.stops.stop_lat.astype(float)))
    zone_dep: dict[int, int] = defaultdict(int)
    for sid, (x, y) in zip(f.stops.stop_id, stops_xy):
        for i in tree.query(Point(x, y), predicate="within"):
            zone_dep[int(i)] += deps.get(str(sid), 0)
            break
    rows = [_row(zones.slugs[i], zones.names.get(zones.slugs[i]) or zones.slugs[i], members.get(i, []), zone_dep.get(i, 0))
            for i in range(len(zones.slugs))]
    return AreaReports(kind="zones", categories=list(cats), radiusMeters=None, departuresDay=day.isoformat(),
                       recorded=_recorded_window(), reportsRecorded=len(reps), rows=_rank(rows), label=LABEL, note=NOTE,
                       provenance=_provenance())


def by_stop(category: str | None, radius: int = STOP_RADIUS_M, limit: int = 50) -> AreaReports:
    if not (5 <= radius <= 300):
        raise invalid("`radius` must be between 5 and 300 metres.")
    cats = categories_for(category)
    reps = _selected(cats)
    f = gtfs.feed()
    deps, day = _departures()
    stops_xy = project_lonlats(zip(f.stops.stop_lon.astype(float), f.stops.stop_lat.astype(float)))
    tree = cKDTree(stops_xy)
    members: dict[int, list[rp.Report]] = defaultdict(list)
    for r in reps:
        d, i = tree.query([r.x, r.y], distance_upper_bound=radius)
        if np.isfinite(d):
            members[int(i)].append(r)
    ids, names = list(f.stops.stop_id), list(f.stops.stop_name)
    lon, lat = f.stops.stop_lon.astype(float).tolist(), f.stops.stop_lat.astype(float).tolist()
    rows = [_row(str(ids[i]), names[i], items, deps.get(str(ids[i]), 0), [lon[i], lat[i]]) for i, items in members.items()]
    return AreaReports(kind="stops", categories=list(cats), radiusMeters=radius, departuresDay=day.isoformat(),
                       recorded=_recorded_window(), reportsRecorded=len(reps), rows=_rank(rows)[: max(1, min(limit, 500))],
                       label=LABEL, note=NOTE, provenance=_provenance())


def to_csv(a: AreaReports) -> str:
    import csv

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["id", "nume", "sesizări", "deschise", "rezolvate", "pondere rezolvate", "cea mai veche deschisă",
                "probleme distincte", f"plecări/zi lucrătoare ({a.departuresDay})"])
    for r in a.rows:
        w.writerow([r.id, r.name, r.total, r.open, r.resolved, "" if r.resolvedShare is None else r.resolvedShare,
                    r.oldestOpenAt or "necunoscut", r.distinctProblems, r.departuresPerDay])
    return "﻿" + buf.getvalue()


# --- R19: road defects on STPT corridors -------------------------------------------------------


@lru_cache(maxsize=2)
def gtfs_shapes(sha: str) -> dict[str, LineString]:
    f = gtfs._FEEDS[sha]
    with zipfile.ZipFile(f.path) as z:
        df = pd.read_csv(io.BytesIO(z.read("shapes.txt")), dtype=str)
    df["seq"] = df["shape_pt_sequence"].astype(int)
    out = {}
    for sid, g in df.sort_values("seq").groupby("shape_id"):
        xy = project_lonlats(zip(g.shape_pt_lon.astype(float), g.shape_pt_lat.astype(float)))
        if len(xy) >= 2:
            out[str(sid)] = LineString(xy)
    return out


@lru_cache(maxsize=2)
def _segments(sha: str, day: date) -> list[dict]:
    """Bus and trolleybus segments between consecutive stops: geometry (metric), routes, departures per day."""
    f = gtfs.feed()
    shapes = gtfs_shapes(sha)
    deps = gtfs.count_by_key(local_midnight(day), local_midnight(day) + timedelta(days=1))
    rtype = dict(zip(f.routes.route_id, f.routes.route_type))
    names = dict(zip(f.stops.stop_id, f.stops.stop_name))
    xy = dict(zip(f.stops.stop_id, project_lonlats(zip(f.stops.stop_lon.astype(float), f.stops.stop_lat.astype(float)))))
    main_shape = (f.trips.groupby(["route_id", "direction_id"])["shape_id"].agg(lambda s: s.value_counts().index[0]).to_dict())
    segs: dict[tuple[str, str], dict] = {}
    for (route, direction), pat in gtfs.stop_patterns().items():
        if rtype.get(route) not in ("3", "11"):  # bus, trolleybus; trams are not STPT road corridors here
            continue
        line = shapes.get(str(main_shape.get((route, direction), "")))
        if line is None:
            continue
        pos = []
        for s in pat.stop_ids:
            p = xy.get(s)
            pos.append(None if p is None else (line.project(Point(p)), line.distance(Point(p))))
        for a, b, pa, pb in zip(pat.stop_ids, pat.stop_ids[1:], pos, pos[1:]):
            if pa is None or pb is None or pa[1] > 60 or pb[1] > 60 or pb[0] - pa[0] < 1:
                continue
            seg = segs.get((a, b))
            n = deps.get((a, route, direction), 0)
            if seg is None:
                geom = substring(line, pa[0], pb[0])
                if not isinstance(geom, LineString) or geom.length < 1:
                    continue
                seg = segs[(a, b)] = {"a": a, "b": b, "geom": geom, "routes": set(), "deps": 0}
            seg["routes"].add(route)
            seg["deps"] += n
    out = []
    for (a, b), s in segs.items():
        s.update(an=names.get(a, a), bn=names.get(b, b))
        out.append(s)
    return out


def road_segments(limit: int = 5) -> tuple[RoadIssues, list[dict]]:
    """(summary with the top `limit` segments, every segment with ≥ 1 pothole incl. WGS84 geometry)."""
    f = gtfs.feed()
    day = working_day()
    segs = _segments(f.sha256, day)
    pots = [r for r in rp.load_reports().values() if r.sub == POTHOLE and r.category == "Străzi și trotuare"]
    tree = STRtree([s["geom"] for s in segs])
    counts: dict[int, int] = defaultdict(int)
    matched = 0
    for r in pots:
        near = tree.query(Point(r.x, r.y), predicate="dwithin", distance=MATCH_M)
        if len(near):
            matched += 1
        for i in near:
            counts[int(i)] += 1
    hit = []
    for i, n in counts.items():
        s = segs[i]
        hit.append({"seg": s, "potholes": n})
    hit.sort(key=lambda h: (-h["seg"]["deps"], -h["potholes"], h["seg"]["a"], h["seg"]["b"]))

    def rec(h) -> RoadSegment:
        s = h["seg"]
        return RoadSegment(segmentId=f"{s['a']}-{s['b']}", fromStopId=s["a"], fromName=s["an"], toStopId=s["b"],
                           toName=s["bn"], routeIds=sorted(s["routes"]), potholes=h["potholes"],
                           departuresPerDay=s["deps"], lengthMeters=int(round(s["geom"].length)))

    summary = RoadIssues(
        label=I18n(ro=f"Gropi raportate pe traseele STPT: din sesizările înregistrate {_recorded_window().start[:10]}–"
                      f"{_recorded_window().end[:10]}; doar numărate", en="Potholes reported on STPT corridors; counted only"),
        recorded=_recorded_window(), departuresDay=day.isoformat(), potholesRecorded=len(pots), potholesOnCorridors=matched,
        matchMeters=MATCH_M, segmentsWithReports=len(hit), segments=[rec(h) for h in hit[: max(1, min(limit, 200))]],
        provenance=_provenance())
    feats = []
    for h in hit:
        r = rec(h)
        g = to_wgs84(h["seg"]["geom"])
        feats.append({"type": "Feature",
                      "geometry": {"type": "LineString", "coordinates": [[round(x, 6), round(y, 6)] for x, y in g.coords]},
                      "properties": r.model_dump()})
    return summary, feats
