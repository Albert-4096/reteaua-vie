"""Conflicts between closures (SPEC §6.1 item 10).

Two closures conflict when their windows overlap and:
- `same_stops`: they take away service at a common stop (rows that count as lost);
- `same_corridor`: their closed segments, each with its buffer, are within 300 m.
`shared_detour` (their detour-load edges intersect) needs the M4 detour-load
module; until it exists it is not checked, and NOTES says so.
"""

from __future__ import annotations

from app.common import state
from app.common.errors import not_found
from app.common.geo import from_geojson, to_metric
from app.common.timeutil import iso, parse_iso
from app.m1_disruption.impact import counts_as_lost
from app.models.base import Window
from app.models.v2 import Conflict

CORRIDOR_METERS = 300.0

NOTES = ("shared_detour: neverificat încă, modulul de ocolire (detour-load, M4) nu există; "
         "not checked yet, the detour-load module (M4) does not exist")


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


def find_conflicts(closure: dict, others: list[dict]) -> list[Conflict]:
    """Conflicts of one closure with the other stored closures."""
    cid = closure["id"]
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
    out.sort(key=lambda c: (c.overlap.start, c.otherClosureId, c.kind))
    return out


def conflicts_for(closure_id: str) -> list[Conflict]:
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id}.")
    return find_conflicts(closure, state.list_all("closures"))
