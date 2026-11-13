"""Conflicts between closures (SPEC §6.1 item 10).

Two closures conflict when their windows overlap and:
- `same_stops`: they take away service at a common stop (rows that count as lost);
- `same_corridor`: their closed segments, each with its buffer, are within 300 m;
- `shared_detour`: their detour-load top edges (M4, app.m4_access.detour) share a stretch of
  street: at least 50 m of one closure's edges within 10 m of the other's. Detour load is a
  slow job, so only results already in the job cache are compared; a pair with a missing
  result is not checked and `conflicts_with_notes` names it (the X-Notes header).
"""

from __future__ import annotations

import json

from shapely.geometry import LineString

from app.common import state
from app.common.errors import not_found
from app.common.geo import from_geojson, to_metric
from app.common.timeutil import iso, parse_iso
from app.m1_disruption.impact import counts_as_lost
from app.models.base import Window
from app.models.v2 import Conflict

CORRIDOR_METERS = 300.0
DETOUR_NEAR_METERS = 10.0
DETOUR_SHARED_METERS = 50.0


def _lost(analysis: dict | None) -> dict[str, set[str]]:
    """{stopId: {routeId}} of the rows that count as lost."""
    out: dict[str, set[str]] = {}
    for r in (analysis or {}).get("stops") or []:
        if counts_as_lost(r):
            out.setdefault(r["stopId"], set()).add(r["routeId"])
    return out


def _routes(closure: dict, analysis: dict | None) -> set[str]:
    ids = {r["routeId"] for r in (analysis or {}).get("stops") or [] if counts_as_lost(r)}
    ids |= {a["routeId"] for a in closure.get("routeActions") or []}
    return ids


def _buffered(closure: dict):
    if not closure.get("geometry"):
        return None
    try:
        return to_metric(from_geojson(closure["geometry"])).buffer(float(closure.get("bufferMeters") or 30))
    except Exception:
        return None


def _detour(closure: dict):
    """(metric union of the top detour edges, {routeIds on them}) from the job cache, or None.

    Only for a closure dict that is the stored closure (a scenario's modified copy has its own
    geometry, so the stored result would be wrong for it).
    """
    try:
        stamp = tuple(_mtime(state.path_for("closures", closure["id"], part))
                      for part in (None, state.PART_ANALYSIS, "decisions"))
    except ValueError:
        return None
    key = (closure["id"], stamp, json.dumps([closure.get("geometry"), closure.get("bufferMeters")]))
    if key in _detour_memo:
        return _detour_memo[key]
    found = _detour_uncached(closure)
    if found is not None:  # a missing result is looked up again: it may be computed meanwhile
        if len(_detour_memo) > 256:
            _detour_memo.clear()
        _detour_memo[key] = found
    return found


def _mtime(path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return None


_detour_memo: dict[tuple, tuple] = {}


def _detour_uncached(closure: dict):
    try:
        from app.m4_access import detour
    except ImportError:
        return None
    try:
        stored = state.read("closures", closure["id"])
    except ValueError:
        stored = None
    if not stored or stored.get("geometry") != closure.get("geometry") \
            or stored.get("bufferMeters") != closure.get("bufferMeters"):
        return None
    result = detour.cached_for(closure["id"])
    if result is None:
        return None
    lines = [to_metric(LineString(e.geometry.coordinates)) for e in result.edges]
    return lines, [set(e.routeIdsOnEdge) for e in result.edges]


def _shared_detour(d1, d2) -> set[str] | None:
    """Routes on the shared detour stretch, or None when the top edges share no street."""
    lines1, routes1 = d1
    lines2, routes2 = d2
    hit = False
    routes: set[str] = set()
    for a, ra in zip(lines1, routes1):
        for b, rb in zip(lines2, routes2):
            shared = max(a.intersection(b.buffer(DETOUR_NEAR_METERS)).length,
                         b.intersection(a.buffer(DETOUR_NEAR_METERS)).length)
            if shared >= DETOUR_SHARED_METERS:
                hit = True
                routes |= ra | rb
    return routes if hit else None


def find_conflicts(closure: dict, others: list[dict], unchecked: list[str] | None = None) -> list[Conflict]:
    """Conflicts of one closure with the other stored closures.

    `unchecked`, when given, collects the ids of overlapping closures whose shared_detour
    could not be checked (a detour load not computed yet, for either side).
    """
    cid = closure["id"]
    det1 = _detour(closure)
    s1, e1 = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    a1 = state.read("closures", cid, state.PART_ANALYSIS)
    lost1 = _lost(a1)
    routes1 = _routes(closure, a1)
    g1 = _buffered(closure)
    out: list[Conflict] = []
    for other in others:
        oid = other["id"]
        if oid == cid:
            continue
        s2, e2 = parse_iso(other["window"]["start"]), parse_iso(other["window"]["end"])
        start, end = max(s1, s2), min(e1, e2)
        if start >= end:
            continue
        overlap = Window(start=iso(start), end=iso(end))
        a2 = state.read("closures", oid, state.PART_ANALYSIS)
        lost2 = _lost(a2)
        shared = sorted(set(lost1) & set(lost2), key=lambda s: (len(s), s))
        if shared:
            rids = sorted(set().union(*(lost1[s] | lost2[s] for s in shared)))
            out.append(Conflict(closureId=cid, otherClosureId=oid, otherTitle=other["title"], overlap=overlap,
                                kind="same_stops", stopIds=shared, routeIds=rids))
        g2 = _buffered(other)
        if g1 is not None and g2 is not None and g1.distance(g2) <= CORRIDOR_METERS:
            out.append(Conflict(closureId=cid, otherClosureId=oid, otherTitle=other["title"], overlap=overlap,
                                kind="same_corridor", stopIds=shared,
                                routeIds=sorted(routes1 | _routes(other, a2))))
        det2 = _detour(other) if det1 is not None else None
        if det1 is None or det2 is None:
            if unchecked is not None:
                unchecked.append(oid)
            continue
        shared_routes = _shared_detour(det1, det2)
        if shared_routes is not None:
            out.append(Conflict(closureId=cid, otherClosureId=oid, otherTitle=other["title"], overlap=overlap,
                                kind="shared_detour", stopIds=[], routeIds=sorted(shared_routes)))
    out.sort(key=lambda c: (c.overlap.start, c.otherClosureId, c.kind))
    return out


def conflicts_for(closure_id: str) -> list[Conflict]:
    return conflicts_with_notes(closure_id)[0]


def conflicts_with_notes(closure_id: str) -> tuple[list[Conflict], str]:
    """(conflicts, X-Notes text in ASCII: which shared_detour pairs were not checked)."""
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id}.")
    unchecked: list[str] = []
    items = find_conflicts(closure, state.list_all("closures"), unchecked)
    if unchecked:
        notes = ("shared_detour not checked against " + ", ".join(sorted(set(unchecked)))
                 + ": detour load not computed yet (GET /api/closures/{id}/detour-load)")
    else:
        notes = "same_stops, same_corridor and shared_detour checked"
    return items, notes
