"""GET /api/closures/{id}/detour-load: DetourLoad (Braess F1) + spillover (F2). CONTRACT marks it J.

The detour load runs as a job (app.common.jobs.respond): 200 when cached or done within 3 s,
else 202 {jobId}. The spillover is added on every 200 answer from our vehicle recording, so it
follows the recording as it grows; it is null for a closure whose window misses the recording.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.common import state
from app.common.errors import not_found
from app.common.jobs import respond
from app.m4_access import detour
from app.m4_access.spillover import with_spillover
from app.models.v2 import DetourLoad

router = APIRouter(tags=["M4 detour load"])


@router.get("/closures/{closure_id}/detour-load", response_model=DetourLoad,
            responses={202: {"description": "Job started: poll /api/jobs/{jobId}"}})
def get_detour_load(closure_id: str):
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id}.")
    out = respond(detour.job_key(closure_id), lambda: detour.compute_detour_load(closure))
    if isinstance(out, JSONResponse):
        return out
    return with_spillover(closure, out)
