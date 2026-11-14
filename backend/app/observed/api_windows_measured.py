"""GET /api/closures/{id}/windows/measured: the closure's windows priced by measured traffic (L2).

A sibling of /windows (same query, unchanged ranking there). A job (app.common.jobs.respond): 200 when
cached or done within 3 s, else 202 {jobId}; the key follows the closure, the register and L0's hours.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.common.jobs import respond
from app.m4_access import windows as win
from app.observed import window_cost
from app.observed.models import MeasuredWindows

router = APIRouter(tags=["L2 measured windows"])


@router.get("/closures/{closure_id}/windows/measured", response_model=MeasuredWindows,
            responses={202: {"description": "Job started: poll /api/jobs/{jobId}"}})
def get_measured_windows(closure_id: str,
                         hours: float | None = Query(None, description="Length of the works in hours"),
                         from_: str | None = Query(None, alias="from", description="Search start (default DEMO_NOW)"),
                         to: str | None = Query(None, description="Search end (default from + 14 days)")):
    win.load_closure(closure_id)
    key = window_cost.job_key(closure_id, hours, from_ or None, to or None)
    return respond(key, lambda: window_cost.suggest(closure_id, hours=hours, start=from_ or None, end=to or None))
