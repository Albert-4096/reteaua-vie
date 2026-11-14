"""GET /api/closures/{id}/detour-cost: the diversion in minutes, planned vs measured vs estimated (L1-B).

A job (app.common.jobs.respond): 200 when cached or done within 3 s, else 202 {jobId}. The cache key
names the closure, its decisions and the L0 hours built, so the answer follows the recording.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.observed import detour_cost
from app.observed.models import DetourCost

router = APIRouter(tags=["L1 detour cost"])


@router.get("/closures/{closure_id}/detour-cost", response_model=DetourCost,
            responses={202: {"description": "Job started: poll /api/jobs/{jobId}"}})
def get_detour_cost(closure_id: str):
    return detour_cost.respond_for(closure_id)
