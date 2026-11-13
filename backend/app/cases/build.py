"""Build the three prepared closures (SPEC §5) from the real STPT notices.

Each closure comes from the notice text through the same parser a clerk uses
(app.m1_disruption.parser), then gets what SPEC §5 fixes for the demo:
  - the id, title, window and lines of app.cases.catalog;
  - the geometry from the OSM extract:
      16dec:   the tram track of Bd. 16 Decembrie 1989 towards Podul Maria, between Piața Iuliu
               Maniu and Piața Maria (the notice gives only „10–15 m”: approximate location);
      e3:      Str. Ardealului between Str. Rahovei and Str. Martir Gogu Opre (from the notice);
      mocioni: Bd. 16 Decembrie 1989 at Piața Alexandru Mocioni („zona …”: approximate location);
  - sourceText and sourceUrl of the real post.
Route actions and the 4b path are the parser's own result on the notice, not typed in here.
Nothing in this file is a figure: every number about a case is computed later from the data.
"""

from __future__ import annotations

import io
import zipfile
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

from shapely.geometry import LineString, MultiLineString, MultiPoint, Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, nearest_points

from app.cases.catalog import CASES, CASES_BY_CLOSURE, Case
from app.common import gtfs, state
from app.common.city import load_network
from app.common.geo import to_geojson, to_metric, to_wgs84
from app.common.stpt_posts import get_post
from app.common.timeutil import iso
from app.config import get_settings, now
from app.m1_disruption import parser
from app.models.base import I18n
from app.models.v1 import Closure, RouteAction

APPROXIMATE = I18n(
    ro="locație aproximativă: anunțul nu dă punctul exact",
    en="approximate location: the notice does not give the exact point",
)


class CaseBuildError(RuntimeError):
    pass


@dataclass
class Built:
    closure: Closure
    unread: list[str]
    approximate: bool
    geometry_note: str


def _stops_named(prefix: str) -> list[dict]:
    p = parser.fold(prefix)
    return [s for s in load_network().stops if parser.fold(s["name"]).startswith(p)]


def _street(name: str):
    st = parser.resolve_street(name)
    if st is None:
        raise CaseBuildError(f"street not in the register: {name}")
    geom = parser.street_geometry(st)
    if geom is None:
        raise CaseBuildError(f"street not in the OSM extract: {st.name}")
    return st, geom


def _toward(line: LineString, target: BaseGeometry) -> bool:
    """True when the line, in its drawn order, ends closer to the target than it starts."""
    tm = to_metric(target)
    start, end = to_metric(Point(line.coords[0])), to_metric(Point(line.coords[-1]))
    return end.distance(tm) < start.distance(tm)


def geometry_16dec() -> tuple[BaseGeometry, str]:
    """Tram track on Bd. 16 Decembrie 1989, the track used towards Podul Maria (Piața Maria end)."""
    _bd, bd = _street("Bulevardul 16 Decembrie 1989")
    _pim, pim = _street("Piața Iuliu Maniu")
    maria_stops = _stops_named("Piața Sfânta Maria")
    if not maria_stops:
        raise CaseBuildError("no GTFS stop named Piața Sfânta Maria")
    maria = MultiPoint([s["location"] for s in maria_stops]).centroid
    a = nearest_points(bd, pim)[0]
    b = nearest_points(bd, maria)[0]
    section = parser.cut_between(bd, a, b, max_gap_m=150)
    if section is None:
        raise CaseBuildError("could not cut Bd. 16 Decembrie 1989 between Piața Iuliu Maniu and Piața Maria")
    rails = [r for r in parser.tram_along(section, max_dist_m=30, min_share=0.3) if _toward(r, maria)]
    if not rails:
        raise CaseBuildError("no tram track towards Piața Maria along Bd. 16 Decembrie 1989")
    clip = to_wgs84(to_metric(section).buffer(35))
    parts = []
    for r in rails:
        g = r.intersection(clip)
        parts += [p for p in getattr(g, "geoms", [g]) if p.geom_type == "LineString" and not p.is_empty]
    merged = linemerge(parts)
    note = (f"OSM railway=tram along Bd. 16 Decembrie 1989 (stops {', '.join(s['id'] for s in maria_stops)} "
            f"mark Piața Maria), {int(to_metric(merged).length)} m")
    return merged, note


def _parsed_geometry(d: parser.ParseDetail) -> BaseGeometry:
    g = d.closure.geometry
    if g is None:
        raise CaseBuildError("the parser found no closed street in the notice")
    return shape(g.model_dump())


# --- Mocioni: the "normal pattern" is GTFS 4.29 (SPEC §5.3) -------------------------------


def _history_zip(version: str) -> Path:
    hits = sorted((get_settings().data_dir / "gtfs-history").glob(f"smtt-{version}_*.zip"))
    if not hits:
        raise CaseBuildError(f"GTFS {version} missing in $DATA_DIR/gtfs-history (SPEC §5.3)")
    return hits[-1]


@lru_cache(maxsize=2)
def normal_patterns(version: str = "4.29") -> dict[tuple[str, int], tuple[str, ...]]:
    """Most common trip pattern per (route, direction) of an older GTFS version."""
    path = _history_zip(version)
    with zipfile.ZipFile(path) as z:
        def read(name: str) -> pd.DataFrame:
            return pd.read_csv(io.BytesIO(z.read(name)), dtype=str, keep_default_na=False)
        trips, st = read("trips.txt"), read("stop_times.txt")
    st["stop_sequence"] = st["stop_sequence"].astype(int)
    seqs = st.sort_values(["trip_id", "stop_sequence"]).groupby("trip_id")["stop_id"].agg(tuple)
    out = {}
    for (route, d), grp in trips.groupby(["route_id", "direction_id"]):
        counts = Counter(seqs[t] for t in grp["trip_id"] if t in seqs.index)
        if counts:
            out[(route, int(d or 0))] = counts.most_common(1)[0][0]
    return out


def mocioni_actions(d: parser.ParseDetail) -> tuple[list[RouteAction], str]:
    """Suspended stops of 11060 per line and direction, on the GTFS 4.29 normal pattern.

    The notice lists the stops that are still served. On the 4.29 pattern, a stop counts as
    suspended when it lies between the listed stops, or beyond them on the side away from the
    city limit, is not named in the list, and is not on the line's current (4.31) pattern either.
    """
    normal = normal_patterns("4.29")
    current = gtfs.stop_patterns()
    names = parser._stop_names()
    out: list[RouteAction] = []
    for sl in d.served_lists:
        r, dd = sl["routeId"], sl["directionId"]
        if dd is None or (r, dd) not in normal:
            continue
        pat = list(normal[(r, dd)])
        scored = [(parser._name_score(n, names.get(s, "")), s) for n in sl["names"] for s in pat]
        hits = {s for sc, s in scored if sc >= 1}
        strong = {s for sc, s in scored if sc >= 2}
        if hits:
            idx = sorted(pat.index(h) for h in hits)
            lo, hi = idx[0], idx[-1]
            region = set(pat[lo:hi + 1])
            if sl["openSide"] == "end":
                region |= set(pat[:lo])
            elif sl["openSide"] == "start":
                region |= set(pat[hi + 1:])
        else:
            region = set(pat)
        now_served = set(current[(r, dd)].stop_ids) if (r, dd) in current else set()
        susp = [s for s in pat if s in region and s not in strong and s not in now_served]
        out.append(RouteAction(routeId=r, directionId=dd, action="rerouted", suspendedStopIds=susp, stopNames=None))
    note = (f"normal pattern = GTFS 4.29 ({_history_zip('4.29').name}); suspended = listed as not served "
            "by notice 11060 and absent from the GTFS 4.31 pattern")
    return out, note


def _approximate(case: Case) -> bool:
    return case.id in ("case_16dec", "case_mocioni")


def build_case(case: Case) -> Built:
    post = get_post(case.post_id)
    if post is None:
        raise CaseBuildError(f"STPT post {case.post_id} is not in the recording ($LIVE_DIR/stpt-posts)")
    d = parser.parse_detail(post.text, reference=post.date)
    direction = "both"
    if case.id == "case_16dec":
        geom, note = geometry_16dec()
        direction = "along"   # drawn towards Podul Maria: only that track is closed
    else:
        geom = _parsed_geometry(d)
        note = "OSM street ways named in the notice (" + ", ".join(s.name for s in d.closure_streets[:3]) + ")"
        if d.section and d.section[0] is not d.section[1]:
            note += f", cut between {d.section[0].name} and {d.section[1].name}"
        elif d.section:
            note += f", within 200 m of {d.section[0].name}"
    actions = [a for a in (d.closure.routeActions or []) if a.routeId in case.route_ids]
    if case.id == "case_mocioni":
        actions, pattern_note = mocioni_actions(d)
        note += "; " + pattern_note
    missing = sorted(set(case.route_ids) - {a.routeId for a in actions})
    if missing:
        raise CaseBuildError(f"{case.id}: the parser found no action for {', '.join(missing)}")
    old = state.read("closures", case.closure_id) or {}
    data = dict(
        id=case.closure_id,
        status=old.get("status") or "draft",
        createdAt=old.get("createdAt") or iso(now()),
        title=case.title,
        kind="notice",
        geometry=to_geojson(geom if isinstance(geom, (LineString, MultiLineString)) else linemerge(geom)),
        bufferMeters=30,
        direction=direction,
        window={"start": case.window_start, "end": case.window_end},
        routeIds=list(case.route_ids),
        sourceText=post.text,
        sourceUrl=post.link or None,
        routeActions=[a.model_dump(mode="json") for a in actions],
        temporaryRoutes=[t.model_dump(mode="json") for t in d.closure.temporaryRoutes or []] or None,
    )
    if _approximate(case) and "locationNote" in Closure.model_fields:
        data["locationNote"] = APPROXIMATE.model_dump()
    return Built(Closure.model_validate(data), d.unread, _approximate(case), note)


def location_note(closure_id: str) -> I18n | None:
    """The „locație aproximativă” label for a prepared closure whose notice gives no exact point."""
    case = CASES_BY_CLOSURE.get(closure_id)
    return APPROXIMATE if case is not None and _approximate(case) else None


def build_all(save: bool = True) -> list[Built]:
    """Build the three closures; with save=True write them to the state store (keeps createdAt/status)."""
    out = []
    for case in CASES:
        b = build_case(case)
        if save:
            state.write("closures", case.closure_id, b.closure)
        out.append(b)
    return out
