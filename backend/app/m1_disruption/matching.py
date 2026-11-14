"""Which (stop, route, direction) rows a closure hits (SPEC §6.1 items 2, 4-6).

Two sources of rows:
- a drawn geometry: buffer matching on the route paths, direction by bearing;
- `routeActions` (a notice or input by line): the stops come from the action,
  confidence starts at 0.9.

Pure functions over the network (city paths, GTFS stop order). Rows are plain
dicts with the AffectedStop fields that do not depend on the timetable
(departuresLost and nearestServed are filled by analysis.py).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from functools import lru_cache
from typing import Any, Iterable

from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring

from app.common import gtfs
from app.m1_disruption.impact import Timetable, current_timetable, timetable_for_closure
from app.common.city import load_network, zone_for_point
from app.common.geo import from_geojson, to_geojson, to_metric, to_wgs84

Key = tuple[str, str, int]

COS45 = math.cos(math.radians(45))
EDGE_METERS = 10.0             # EDGE_OF_BUFFER: within this of the buffer edge
ACTION_CONFIDENCE = 0.9        # rows from routeActions start here (SPEC §6.1 item 6)
AFFECTED_THRESHOLD = 0.75
KEEP_NEAR_METERS = 120.0       # "shortened": a stop this close to a kept stop is kept (other side of the street)
OTHER_SIDE_METERS = 200.0      # input by line, both directions: endpoint of the opposite direction
SINGLE_STOP_SECTION_M = 40.0   # geometry fill around a single suspended stop


# --- names -----------------------------------------------------------------------


def norm(text: str | None) -> str:
    """Lowercase, no diacritics, single spaces (for name matching)."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9()]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def base_name(text: str | None) -> str:
    """'Opre Gogu (Ardealului)' -> 'opre gogu'."""
    return norm((text or "").split("(")[0])


@lru_cache(maxsize=1)
def _name_counts() -> Counter:
    return Counter(norm(s["name"]) for s in load_network().stops)


def is_duplicate_name(name: str) -> bool:
    """The exact stop name is used by more than one stop id in the network."""
    return _name_counts()[norm(name)] > 1


# --- network geometry (metric, cached) -----------------------------------------------


@lru_cache(maxsize=256)
def path_metric(route_id: str, direction_id: int) -> LineString | None:
    line = load_network().path_lines.get((route_id, int(direction_id)))
    return to_metric(line) if line is not None else None


@lru_cache(maxsize=4096)
def stop_metric(stop_id: str) -> Point | None:
    s = load_network().stop_by_id.get(stop_id)
    if s is None:
        return None
    return to_metric(Point(*s["location"]))


def route_short_name(route_id: str) -> str:
    r = load_network().route_by_id.get(route_id)
    return r["shortName"] if r else route_id


def directions_of(route_id: str, tt: Timetable | None = None) -> list[int]:
    return sorted(d for (r, d) in (tt or current_timetable()).stop_patterns() if r == route_id)


def _unit(dx: float, dy: float) -> tuple[float, float]:
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 1e-9 else (0.0, 0.0)


def tangent(line: LineString, dist: float, step: float = 10.0) -> tuple[float, float]:
    """Unit direction of a metric line at a distance along it (its coordinate order)."""
    d0, d1 = max(0.0, dist - step), min(line.length, dist + step)
    a, b = line.interpolate(d0), line.interpolate(d1)
    return _unit(b.x - a.x, b.y - a.y)


def _parts(geom: BaseGeometry) -> list[LineString]:
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return list(geom.geoms)
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, LineString)]


# --- row construction ------------------------------------------------------------


def confidence(reasons: Iterable[str], start: float = 0.5) -> float:
    """SPEC §6.1 item 6, clamped to 0..1."""
    r = set(reasons)
    c = start
    if start < ACTION_CONFIDENCE:
        if "IN_BUFFER" in r and "ON_ROUTE_PATH" in r:
            c += 0.2
        if "DIRECTION_MATCH" in r:
            c += 0.15
        if "NAMED_IN_NOTICE" in r:
            c += 0.15
    if "DUPLICATE_STOP_NAME" in r:
        c -= 0.15
    if "EDGE_OF_BUFFER" in r:
        c -= 0.2
    if "DIRECTION_UNCLEAR" in r:
        c -= 0.25
    if "NOT_NAMED_IN_NOTICE" in r or "ROUTE_NOT_IN_NOTICE" in r:
        c -= 0.3
    return round(min(1.0, max(0.0, c)), 2)


_REASON_ORDER = ("IN_BUFFER", "ON_ROUTE_PATH", "DIRECTION_MATCH", "DIRECTION_UNCLEAR", "EDGE_OF_BUFFER",
                 "DUPLICATE_STOP_NAME", "NAMED_IN_NOTICE", "NOT_NAMED_IN_NOTICE", "ROUTE_NOT_IN_NOTICE")


def make_row(stop_id: str, route_id: str, direction_id: int, reasons: Iterable[str], start: float,
             tt: Timetable | None = None) -> dict:
    n = load_network()
    s = n.stop_by_id[stop_id]
    pat = (tt or current_timetable()).stop_patterns().get((route_id, int(direction_id)))
    rs = [r for r in _REASON_ORDER if r in set(reasons)]
    conf = confidence(rs, start)
    return {
        "stopId": stop_id,
        "name": s["name"],
        "location": s["location"],
        "zoneSlug": zone_for_point(*s["location"]),
        "routeId": route_id,
        "routeShortName": route_short_name(route_id),
        "directionId": int(direction_id),
        "headsign": pat.headsign if pat else None,
        "state": "affected" if conf >= AFFECTED_THRESHOLD else "unsure",
        "confidence": conf,
        "reasons": rs,
        "confirmed": None,
        "departuresLost": None,
        "nearestServed": None,
    }


def merge_rows(rows: Iterable[dict]) -> list[dict]:
    """One row per (stop, route, direction): keep the most confident one."""
    best: dict[Key, dict] = {}
    for r in rows:
        k = (r["stopId"], r["routeId"], r["directionId"])
        if k not in best or r["confidence"] > best[k]["confidence"]:
            best[k] = r
    return list(best.values())


# --- notice text helpers -----------------------------------------------------------------


_TERMINUS_RE = re.compile(r"\b(?:catre|spre|sens(?:ul)?|directia)\s+([a-z0-9 ]{3,40})")


def notice_termini(text: str | None) -> list[str]:
    """Normalised phrases after 'către / spre / sensul / direcția' in a notice."""
    return [m.group(1).strip() for m in _TERMINUS_RE.finditer(norm(text))]


def headsign_named(headsign: str | None, termini: list[str]) -> bool:
    hb = base_name(headsign)
    if not hb:
        return False
    return any(hb in t or (len(t) >= 4 and t in hb) for t in termini)


def stop_named(name: str, text_norm: str) -> bool:
    b = base_name(name)
    return bool(b) and len(b) >= 4 and b in text_norm


# --- drawn closures ---------------------------------------------------------------


def match_drawn(closure: dict, tt: Timetable | None = None) -> list[dict]:
    """Rows for a drawn geometry (SPEC §6.1 items 4-6)."""
    tt = tt or timetable_for_closure(closure)
    geom = closure.get("geometry")
    if not geom:
        return []
    g = to_metric(from_geojson(geom))
    parts = _parts(g)
    if not parts:
        return []
    buf = float(closure.get("bufferMeters") or 30)
    want = closure.get("direction") or "both"
    kind = closure.get("kind") or "drawn"
    route_filter = set(closure.get("routeIds") or [])
    text = closure.get("sourceText") if kind == "notice" else None
    text_norm = norm(text)
    termini = notice_termini(text)

    rows = []
    for (route_id, direction_id), pat in tt.stop_patterns().items():
        if kind == "drawn" and route_filter and route_id not in route_filter:
            continue
        path = path_metric(route_id, direction_id)
        if path is None or path.distance(g) > buf:
            continue
        for stop_id in pat.stop_ids:
            pt = stop_metric(stop_id)
            if pt is None:
                continue
            dist = pt.distance(g)
            if dist > buf:
                continue
            along = path.project(pt)
            proj = path.interpolate(along)
            if proj.distance(g) > buf + 1e-6:
                continue  # the stop is near the closure but its place on the path is not
            reasons = ["IN_BUFFER", "ON_ROUTE_PATH"]
            if dist > buf - EDGE_METERS:
                reasons.append("EDGE_OF_BUFFER")
            # direction: path bearing vs drawn bearing at the closest point
            part = min(parts, key=lambda p: p.distance(proj))
            tp = tangent(path, along)
            td = tangent(part, part.project(proj))
            cos = tp[0] * td[0] + tp[1] * td[1]
            rel = "along" if cos > COS45 else "against" if cos < -COS45 else "unclear"
            if want != "both" and rel != "unclear" and rel != want:
                continue
            reasons.append("DIRECTION_MATCH" if rel != "unclear" else "DIRECTION_UNCLEAR")
            if kind == "notice":
                if termini and headsign_named(pat.headsign, termini):
                    reasons.append("NAMED_IN_NOTICE")
                    if "DIRECTION_UNCLEAR" in reasons:
                        reasons[reasons.index("DIRECTION_UNCLEAR")] = "DIRECTION_MATCH"
                name = load_network().stop_by_id[stop_id]["name"]
                if text_norm and stop_named(name, text_norm):
                    if "NAMED_IN_NOTICE" not in reasons:
                        reasons.append("NAMED_IN_NOTICE")
                    if is_duplicate_name(name):
                        reasons.append("DUPLICATE_STOP_NAME")
                elif text_norm and "NAMED_IN_NOTICE" not in reasons:
                    reasons.append("NOT_NAMED_IN_NOTICE")
                if route_filter and route_id not in route_filter:
                    reasons.append("ROUTE_NOT_IN_NOTICE")
            rows.append(make_row(stop_id, route_id, direction_id, reasons, 0.5, tt))
    return merge_rows(rows)


# --- route actions --------------------------------------------------------------------


def resolve_name(name: str, route_id: str, direction_id: int,
                 tt: Timetable | None = None) -> tuple[list[str], bool]:
    """Stop ids for a notice stop name on one (route, direction).

    Exact name on the route's stop order first, then the name without the
    parenthesis, then any stop of the route in the network with that name.
    Returns (ids, ambiguous).
    """
    n = load_network()
    order = (tt or current_timetable()).stop_order(route_id, direction_id)
    full, base = norm(name), base_name(name)
    paren = norm(name.split("(", 1)[1]) if "(" in name else ""
    hits = [s for s in order if norm(n.stop_by_id[s]["name"]) == full]
    if not hits and base:
        hits = [s for s in order if base_name(n.stop_by_id[s]["name"]) == base]
        if len(hits) > 1 and paren:
            narrowed = [s for s in hits if paren in norm(n.stop_by_id[s]["name"])]
            hits = narrowed or hits
    if not hits:
        cands = [s["id"] for s in n.stops if route_id in s["routeIds"]
                 and (norm(s["name"]) == full or (base and base_name(s["name"]) == base))]
        path = path_metric(route_id, direction_id)
        other = [d for d in directions_of(route_id, tt) if d != direction_id]
        other_path = path_metric(route_id, other[0]) if other else None
        for sid in cands:
            pt = stop_metric(sid)
            if path is None or pt is None:
                continue
            # a stop missing from the common pattern: keep it if it sits on this direction's side
            if other_path is None or pt.distance(path) <= pt.distance(other_path):
                hits.append(sid)
    return hits, len(hits) > 1


def _nearest_in(order: list[str], stop_id: str) -> str | None:
    """Stop of `order` that is the same stop or the other side of the street."""
    n = load_network()
    target = n.stop_by_id.get(stop_id)
    if target is None:
        return None
    if stop_id in order:
        return stop_id
    tb = base_name(target["name"])
    pt = stop_metric(stop_id)
    best, best_d = None, OTHER_SIDE_METERS
    for s in order:
        d = stop_metric(s).distance(pt)
        if base_name(n.stop_by_id[s]["name"]) == tb and d <= OTHER_SIDE_METERS * 2:
            d = min(d, 1.0)
        if d <= best_d:
            best, best_d = s, d
    return best


def action_stops(action: dict, tt: Timetable | None = None) -> tuple[dict[int, list[str]], set[Key], list[str]]:
    """Suspended stops per direction for one RouteAction.

    Returns ({directionId: [stop ids in travel order]}, ambiguous keys, unresolved names).
    """
    n = load_network()
    tt = tt or current_timetable()
    route_id = action["routeId"]
    dirs = [action["directionId"]] if action.get("directionId") is not None else directions_of(route_id, tt)
    kind = action["action"]
    out: dict[int, list[str]] = {}
    ambiguous: set[Key] = set()
    unresolved: list[str] = []
    # stopNames are the raw notice names; resolve them only when the action has no ids
    ids_given = {"suspended": action.get("fromStopId") or action.get("toStopId"),
                 "shortened": action.get("keepStopIds"),
                 "rerouted": action.get("suspendedStopIds")}.get(kind)
    names = [] if ids_given else (action.get("stopNames") or [])
    one_dir = action.get("directionId") is not None

    def by_names(d: int) -> list[str]:
        ids = []
        for nm in names:
            hits, amb = resolve_name(nm, route_id, d, tt)
            ids += hits
            if amb:
                ambiguous.update((h, route_id, d) for h in hits)
        return ids

    name_hits: dict[int, list[str]] = {d: by_names(d) for d in dirs} if names else {}
    if names:
        for nm in names:
            if not any(resolve_name(nm, route_id, d, tt)[0] for d in dirs):
                unresolved.append(nm)

    for d in dirs:
        order = tt.stop_order(route_id, d)
        if not order:
            continue
        if kind == "suspended":
            f, t = action.get("fromStopId"), action.get("toStopId")
            if f or t:
                fi = _nearest_in(order, f) if f else order[0]
                ti = _nearest_in(order, t) if t else order[-1]
                if fi is None or ti is None:
                    continue
                i, j = order.index(fi), order.index(ti)
                if i > j:
                    i, j = j, i
                out[d] = order[i:j + 1]
            elif names:
                out[d] = [s for s in order if s in set(name_hits[d])] + \
                         [s for s in name_hits[d] if s not in order]
            else:
                out[d] = list(order)
        elif kind == "shortened":
            keep_ids = set(action.get("keepStopIds") or []) | (set(name_hits.get(d, [])) if names else set())
            keep_ids = {k for k in keep_ids if k in n.stop_by_id}
            if one_dir and action.get("keepStopIds"):
                kept = keep_ids  # ids for this direction: take them as given
            else:
                # ids may belong to the other direction: keep the same stop across the street too
                keep_names = {norm(n.stop_by_id[k]["name"]) for k in keep_ids}
                keep_pts = [stop_metric(k) for k in keep_ids]
                kept = {s for s in order if s in keep_ids or norm(n.stop_by_id[s]["name"]) in keep_names
                        or any(stop_metric(s).distance(k) <= KEEP_NEAR_METERS for k in keep_pts)}
            if not keep_ids:
                continue  # nothing to keep known: do not guess the whole line away
            out[d] = [s for s in order if s not in kept]
        elif kind == "rerouted":
            ids = set(action.get("suspendedStopIds") or [])
            hits = [s for s in order if s in ids]
            if names:
                hits += [s for s in name_hits.get(d, []) if s not in hits]
            # ids given for the other direction only: map them to this side of the street
            if not one_dir and ids and not names and not hits:
                for sid in ids:
                    if sid not in order:
                        m = _nearest_in(order, sid)
                        if m and m not in hits and base_name(n.stop_by_id[m]["name"]) == base_name(
                                n.stop_by_id[sid]["name"]):
                            hits.append(m)
            # ids given for this direction that only a rarer pattern serves (Mocioni M38, M46): keep them
            rare = [s for s in action.get("suspendedStopIds") or [] if s not in order and s not in hits] if one_dir else []
            out[d] = [s for s in order if s in set(hits)] + [s for s in hits if s not in order] + rare
    return out, ambiguous, unresolved


def rows_from_actions(closure: dict, tt: Timetable | None = None) -> tuple[list[dict], list[str]]:
    """Rows for `routeActions` (confidence 0.9). Returns (rows, unresolved stop names)."""
    tt = tt or timetable_for_closure(closure)
    kind = closure.get("kind") or "drawn"
    rows, unresolved = [], []
    for action in closure.get("routeActions") or []:
        if action["routeId"] not in load_network().route_by_id:
            unresolved.append(action["routeId"])
            continue
        per_dir, ambiguous, unres = action_stops(action, tt)
        unresolved += unres
        # "shortened" whose kept names did not all resolve: which stops are dropped is a guess
        names = set(action.get("stopNames") or [])
        guessed = action["action"] == "shortened" and bool(names) and (
            bool(unres) or (bool(action.get("keepStopIds")) and len(set(action["keepStopIds"])) < len(names)))
        for d, stops in per_dir.items():
            for s in stops:
                reasons = ["ON_ROUTE_PATH"]
                if guessed:
                    reasons.append("NOT_NAMED_IN_NOTICE")
                elif kind == "notice":
                    reasons.append("NAMED_IN_NOTICE")
                if (s, action["routeId"], d) in ambiguous:
                    reasons.append("DUPLICATE_STOP_NAME")
                rows.append(make_row(s, action["routeId"], d, reasons, ACTION_CONFIDENCE, tt))
    return merge_rows(rows), unresolved


def match_closure(closure: dict) -> tuple[list[dict], list[str]]:
    """All rows of a closure: from routeActions when present, else from the geometry.

    Stop order comes from the timetable in force before the works (impact.timetable_for).
    """
    tt = timetable_for_closure(closure)
    if closure.get("routeActions"):
        return rows_from_actions(closure, tt)
    return match_drawn(closure, tt), []


# --- geometry for input by line -----------------------------------------------------


def _section(path: LineString, stops: list[str]) -> LineString | None:
    pos = sorted(path.project(stop_metric(s)) for s in stops if stop_metric(s) is not None)
    if not pos:
        return None
    a, b = pos[0], pos[-1]
    if b - a < 1.0:
        a, b = max(0.0, a - SINGLE_STOP_SECTION_M), min(path.length, b + SINGLE_STOP_SECTION_M)
    seg = substring(path, a, b)
    return seg if isinstance(seg, LineString) and seg.length > 0 else None


def geometry_from_actions(actions: list[dict], tt: Timetable | None = None) -> dict[str, Any] | None:
    """GeoJSON (LineString or MultiLineString) of the route path along the suspended stops.

    One section per run of consecutive suspended stops, per route and direction.
    """
    tt = tt or current_timetable()
    lines: list[LineString] = []
    for action in actions:
        if action["routeId"] not in load_network().route_by_id:
            continue
        per_dir, _, _ = action_stops(action, tt)
        for d, stops in per_dir.items():
            path = path_metric(action["routeId"], d)
            order = tt.stop_order(action["routeId"], d)
            if path is None or not stops:
                continue
            idx = sorted(order.index(s) for s in stops if s in order)
            run: list[int] = []
            for i in idx:
                if run and i != run[-1] + 1:
                    sec = _section(path, [order[k] for k in run])
                    if sec is not None:
                        lines.append(sec)
                    run = []
                run.append(i)
            if run:
                sec = _section(path, [order[k] for k in run])
                if sec is not None:
                    lines.append(sec)
    if not lines:
        return None
    wgs = [to_wgs84(line) for line in lines]
    geom = wgs[0] if len(wgs) == 1 else MultiLineString(wgs)
    return to_geojson(geom)
