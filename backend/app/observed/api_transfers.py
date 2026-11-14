"""GET /api/transfers?hub=: transfers at hubs, timetable vs. our recording (A11, from L0).

A job (app.common.jobs.respond): 200 when cached or done within 3 s, else 202 {jobId}.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.observed import transfers
from app.observed.models import TransferReport

router = APIRouter(tags=["A11 transfers"])


@router.get("/transfers", response_model=TransferReport,
            responses={202: {"description": "Job started: poll /api/jobs/{jobId}"}})
def get_transfers(hub: str | None = Query(None, description="One hub (hubId); default: the busiest hubs")):
    return transfers.respond_for(hub or None)
