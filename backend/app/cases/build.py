"""Build the three prepared closures (SPEC §5) from the real STPT notices.

Each closure comes from the notice text through the same parser a clerk uses
(app.m1_disruption.parser), then gets what SPEC §5 fixes for the demo:
  - the id, title, window and lines of app.cases.catalog;
  - the geometry from the OSM extract:
      16dec:   the tram track of Bd. 16 Decembrie 1989 towards Podul Maria just past the Piața Maria
               junction, where lines 2, 4 and 7 share it and lines 1 and 8 have turned off, as long
               as the notice says („10–15 m”: approximate location);
      e3:      Str. Ardealului between Str. Rahovei and Str. Martir Gogu Opre (from the notice);
      mocioni: Bd. 16 Decembrie 1989 at Piața Alexandru Mocioni („zona …”: approximate location);
  - sourceText and sourceUrl of the real post.
Route actions and the 4b path are the parser's own result on the notice, not typed in here.
Nothing in this file is a figure: every number about a case is computed later from the data.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

from shapely.geometry import LineString, MultiLineString, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, substring

from app.cases.catalog import CASES, CASES_BY_CLOSURE, Case
from app.common import gtfs, state
from app.common.city import load_network, route_mode
from app.common.geo import to_geojson, to_metric, to_wgs84
from app.common.stpt_posts import get_post
from app.common.timeutil import iso
from app.config import get_settings, now
from app.m1_disruption import matching, parser
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


LENGTH_RE = re.compile(r"(\d+)\s*m\s*[-–]\s*(\d+)\s*m\b")
SAME_TRACK_M = 5.0      # a line "runs here" when its path is this close
BUFFER_M = 30.0         # the closure's bufferMeters


def geometry_16dec(case: Case, text: str) -> tuple[BaseGeometry, str]:
    """The works on Bd. 16 Decembrie 1989 towards Podul Maria, at the Piața Maria junction (T11).

    The notice gives no point, only a length („aproximativ 10 m – 15 m”). It stops or turns back
    the case's lines (2, 4, 7) and leaves the other tram lines (1, 8) running, so the works sit where
    the case's lines share the track and the others have turned off: along line 2 eastbound, from the
    first point past its Piața Maria stop where every case line runs within 5 m and every other tram
    line is farther than the 30 m buffer, for the longest length the notice gives.
    """
    found = LENGTH_RE.search(text or "")
    if found is None:
        raise CaseBuildError("the notice gives no length „N m – M m” for the works")
    length = float(max(int(found.group(1)), int(found.group(2))))
    base = ("R_TV_2", 0)  # line 2 eastbound: Piața Maria → Catedrala, along Bd. 16 Decembrie 1989
    path = matching.path_metric(*base)
    maria_ids = {s["id"] for s in _stops_named("Piața Sfânta Maria")}
    maria = [s for s in gtfs.stop_patterns()[base].stop_ids if s in maria_ids]
    if path is None or not maria:
        raise CaseBuildError("line 2 eastbound has no path or no Piața Sfânta Maria stop")
    trams = {r for r, _d in load_network().path_lines if route_mode(r) == "tram"}
    paths = {r: [p for p in (matching.path_metric(r, 0), matching.path_metric(r, 1)) if p is not None] for r in trams}
    others = trams - set(case.route_ids)

    def gap(route_id: str, x: float) -> float:
        pt = path.interpolate(x)
        return min(p.distance(pt) for p in paths[route_id])

    x0 = path.project(matching.stop_metric(maria[0]))
    start = next((x0 + k for k in range(int(path.length - x0))
                  if all(gap(r, x0 + k) <= SAME_TRACK_M for r in case.route_ids)
                  and all(gap(r, x0 + k) > BUFFER_M for r in others)), None)
    if start is None:
        raise CaseBuildError("no track past Piața Maria that only the notice's lines use")
    seg = substring(path, start, start + length)
    _bd, bd = _street("Bulevardul 16 Decembrie 1989")
    if to_metric(bd).distance(seg) > SAME_TRACK_M * 3:
        raise CaseBuildError("the junction section is not on Bd. 16 Decembrie 1989")
    note = (f"line 2 eastbound path, {int(start - x0)} m past stop {maria[0]} (Piața Maria): lines "
            f"{', '.join(sorted(case.route_ids))} share the track, {', '.join(sorted(others))} are > {BUFFER_M:.0f} m away; "
            f"{length:.0f} m, the longest length the notice gives")
    return to_wgs84(seg), note


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
        geom, note = geometry_16dec(case, post.text)
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
