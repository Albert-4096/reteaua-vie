"""Step 2 "Decizi" endpoints: time windows and phasing, scenarios, compare (SPEC §6.4, D-009).

Slow answers go through the job helper: 200 when cached or done within 3 s, else 202 {jobId}.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.common.jobs import closure_fingerprint, respond
from app.config import now
from app.common.timeutil import iso
from app.m4_access import compare as cmp
from app.m4_access import windows as win
from app.models.v1 import Compare
from app.models.v2 import JobAccepted, WindowSuggestion

router = APIRouter(tags=["M4 decide"])

ACCEPTED = {202: {"model": JobAccepted, "description": "Still computing: poll GET /api/jobs/{jobId}"}}


@router.get("/closures/{closure_id}/windows", response_model=WindowSuggestion, responses=ACCEPTED)
def get_windows(closure_id: str,
                hours: float | None = Query(None, description="Length of the works in hours (default: the closure's)"),
                from_: str | None = Query(None, alias="from", description="Search start (default DEMO_NOW)"),
                to: str | None = Query(None, description="Search end (default from + 14 days, max 90)"),
                phases: int = Query(1, ge=1, le=win.MAX_PHASES)):
    closure, _ = win.load_closure(closure_id)
    key = (f"windows:v1:{closure_id}:{closure_fingerprint(closure_id)}:{win.others_fingerprint()}:"
           f"{hours}:{from_ or iso(now())}:{to}:{phases}")
    return respond(key, lambda: win.suggest(closure_id, hours=hours, start=from_ or None, end=to or None,
                                            phases=phases))


@router.get("/compare", response_model=Compare)
def get_compare(a: str = Query(..., description="Closure id A"), b: str = Query(..., description="Closure id B")):
    return cmp.compare_closures(a, b)
