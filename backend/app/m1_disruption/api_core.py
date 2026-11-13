"""M1 core endpoints: closures, analysis, human decisions, impact, conflicts.

Thin routers over closures/analysis/impact/conflicts; mounted under /api by app.main.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.common import state
from app.common.city import load_network
from app.common.errors import conflict, invalid, not_found
from app.common.timeutil import iso, parse_iso
from app.config import now
from app.m1_disruption import analysis as an
from app.m1_disruption import conflicts as cf
from app.m1_disruption import impact as imp
from app.m1_disruption import matching
from app.models.v1 import Analysis, Closure, ClosureInput, Impact, StopDecisions
from app.models.v2 import Conflict

router = APIRouter(tags=["M1 closures"])

# load the GTFS index, walking graph and population grid now, so the first
# live draw is as fast as the next ones (SPEC §10: < 3 s)
imp.warm_in_background()


def _load(closure_id: str) -> dict:
    try:
        c = state.read("closures", closure_id)
    except ValueError:
        c = None
    if c is None:
        raise not_found(f"No closure {closure_id}.")
    return c


def validate_input(body: ClosureInput) -> dict:
    """Checks beyond the schema; fills the geometry for input by line. Returns the closure dict."""
    data = body.model_dump(mode="json", by_alias=True)
    if parse_iso(data["window"]["end"]) <= parse_iso(data["window"]["start"]):
        raise invalid("window.end must be after window.start.")
    if not (0 < float(data["bufferMeters"]) <= 500):
        raise invalid("bufferMeters must be between 0 and 500.")
    n = load_network()
    for i, a in enumerate(data.get("routeActions") or []):
        if a["routeId"] not in n.route_by_id:
            raise invalid(f"routeActions[{i}].routeId: unknown route {a['routeId']}.")
        for f in ("fromStopId", "toStopId"):
            if a.get(f) and a[f] not in n.stop_by_id:
                raise invalid(f"routeActions[{i}].{f}: unknown stop {a[f]}.")
        for f in ("keepStopIds", "suspendedStopIds"):
            bad = [s for s in a.get(f) or [] if s not in n.stop_by_id]
            if bad:
                raise invalid(f"routeActions[{i}].{f}: unknown stops {', '.join(bad[:5])}.")
    for rid in data.get("routeIds") or []:
        if rid not in n.route_by_id:
            raise invalid(f"routeIds: unknown route {rid}.")
    if data.get("geometry") is None:
        if not data.get("routeActions"):
            raise invalid("geometry is required unless routeActions describe the closure (input by line).")
        data["geometry"] = matching.geometry_from_actions(data["routeActions"],
                                                          imp.timetable_for(data["window"]["start"]))
        if data["geometry"] is None:
            raise invalid("Could not build a geometry from routeActions: no stop of those lines matched.")
    return data


@router.post("/closures", response_model=Closure, status_code=201)
def create_closure(body: ClosureInput) -> Closure:
    data = validate_input(body)
    data.update(id=state.new_id("cl"), status="draft", createdAt=iso(now()))
    closure = Closure.model_validate(data)
    state.write("closures", closure.id, closure)
    return closure


@router.get("/closures/{closure_id}", response_model=Closure)
def get_closure(closure_id: str) -> Closure:
    return Closure.model_validate(_load(closure_id))


@router.post("/closures/{closure_id}/analyze", response_model=Analysis)
def analyze(closure_id: str) -> Analysis:
    closure = _load(closure_id)
    if closure.get("status") == "published":
        raise conflict(f"Closure {closure_id} is already published.", code="ALREADY_PUBLISHED")
    return an.analyze_closure(closure)


@router.get("/closures/{closure_id}/analysis", response_model=Analysis)
def get_analysis(closure_id: str) -> Analysis:
    _load(closure_id)
    a = an.get_analysis(closure_id)
    if a is None:
        raise not_found(f"Closure {closure_id} was never analyzed.", code="NOT_ANALYZED")
    return a


@router.patch("/closures/{closure_id}/stops", response_model=Analysis)
def decide(closure_id: str, body: StopDecisions) -> Analysis:
    return an.apply_decisions(closure_id, [d.model_dump() for d in body.decisions])


@router.get("/closures/{closure_id}/impact", response_model=Impact)
def get_impact(closure_id: str) -> Impact:
    return imp.compute_impact(closure_id)


@router.get("/closures/{closure_id}/conflicts", response_model=list[Conflict])
def get_conflicts(closure_id: str, response: Response) -> list[Conflict]:
    items, notes = cf.conflicts_with_notes(closure_id)
    response.headers["X-Notes"] = notes
    return items
