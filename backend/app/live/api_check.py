"""Step 4 (monitor) endpoints:
GET /api/closures/{id}/live              LiveCheck from our vehicle recording (SPEC §6.8)
GET /api/closures/{id}/reports?radius=   ReportSummary of the sesizări around it (SPEC §6.9)
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.live.check import compute_live_check
from app.live.reports import report_summary
from app.models.v1 import LiveCheck
from app.models.v2 import ReportSummary

router = APIRouter(tags=["live"])


@router.get("/closures/{closure_id}/live", response_model=LiveCheck)
def closure_live(closure_id: str) -> LiveCheck:
    return LiveCheck.model_validate(compute_live_check(closure_id))


@router.get("/closures/{closure_id}/reports", response_model=ReportSummary)
def closure_reports(closure_id: str,
                    radius: float = Query(500.0, description="metres around the closure, 1-5000")) -> ReportSummary:
    return ReportSummary.model_validate(report_summary(closure_id, radius))
