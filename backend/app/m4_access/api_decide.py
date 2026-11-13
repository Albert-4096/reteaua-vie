"""Step 2 "Decizi" endpoints: time windows and phasing, scenarios, compare (SPEC §6.4, D-009).

Slow answers go through the job helper: 200 when cached or done within 3 s, else 202 {jobId}.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.common.jobs import respond
from app.m4_access import compare as cmp
from app.m4_access import scenarios as sc
from app.m4_access import windows as win
from app.models.v1 import Compare
from app.models.v2 import JobAccepted, Scenario, ScenarioCompare, ScenarioImpact, ScenarioInput, WindowSuggestion

router = APIRouter(tags=["M4 decide"])

ACCEPTED = {202: {"model": JobAccepted, "description": "Still computing: poll GET /api/jobs/{jobId}"}}


@router.get("/closures/{closure_id}/windows", response_model=WindowSuggestion, responses=ACCEPTED)
def get_windows(closure_id: str,
                hours: float | None = Query(None, description="Length of the works in hours (default: the closure's)"),
                from_: str | None = Query(None, alias="from", description="Search start (default DEMO_NOW)"),
                to: str | None = Query(None, description="Search end (default from + 14 days, max 90)"),
                phases: int = Query(1, ge=1, le=win.MAX_PHASES)):
    win.load_closure(closure_id)
    key = win.job_key(closure_id, hours, from_ or None, to or None, phases)
    return respond(key, lambda: win.suggest(closure_id, hours=hours, start=from_ or None, end=to or None,
                                            phases=phases))


@router.get("/compare", response_model=Compare)
def get_compare(a: str = Query(..., description="Closure id A"), b: str = Query(..., description="Closure id B")):
    return cmp.compare_closures(a, b)


@router.post("/scenarios", response_model=Scenario)
def post_scenario(body: ScenarioInput):
    return sc.create(body)


@router.get("/scenarios", response_model=list[Scenario])
def list_scenarios(closureId: str = Query(..., description="The closure whose scenarios to list")):
    return sc.list_for(closureId)


@router.get("/scenarios/compare", response_model=ScenarioCompare, responses=ACCEPTED)
def compare_scenarios(a: str = Query(..., description="Scenario id A"), b: str = Query(..., description="Scenario id B")):
    return respond(sc.compare_job_key(a, b), lambda: sc.compare(a, b))


@router.get("/scenarios/{scenario_id}/impact", response_model=ScenarioImpact, responses=ACCEPTED)
def scenario_impact(scenario_id: str):
    return respond(sc.impact_job_key(scenario_id), lambda: sc.compute_impact(scenario_id))
