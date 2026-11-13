"""Step 4 (monitor) endpoints:
GET /api/closures/{id}/live              LiveCheck from our vehicle recording (SPEC §6.8)
GET /api/closures/{id}/reports?radius=   ReportSummary of the sesizări around it (SPEC §6.9)
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from app.live.check import compute_live_check
from app.live.reports import report_summary
from app.models import v1, v2
from app.models.base import I18n, IsoTime, Model

router = APIRouter(tags=["live"])

# CONTRACT 2.3 optional fields (asked of the models owner); used until app.models has them.
if "stopsUnknown" in v1.LiveSummary.model_fields:
    LiveCheck = v1.LiveCheck
else:
    class LiveSummary(v1.LiveSummary):
        stopsUnknown: int | None = None

    class LiveObservation(v1.LiveObservation):
        state: Literal["skipped", "served", "unknown"] | None = None
        evidence: Literal["stopped_at", "gps"] | None = None

    class LiveStopRow(Model):
        stopId: str
        name: str | None
        routeId: str
        directionId: Literal[0, 1]
        skipped: int
        served: int
        unknown: int

    class LiveCheck(v1.LiveCheck):  # type: ignore[no-redef]
        source: Literal["live", "replay"] | None
        observations: list[LiveObservation]
        summary: LiveSummary
        byStop: list[LiveStopRow] | None = None
        recordedFrom: IsoTime | None = None
        recordedTo: IsoTime | None = None
        label: I18n | None = None
        method: I18n | None = None
        note: I18n | None = None

if "coveredFrom" in v2.ReportSummary.model_fields:
    ReportSummary = v2.ReportSummary
else:
    class ReportSummary(v2.ReportSummary):  # type: ignore[no-redef]
        total: int | None
        coveredFrom: IsoTime | None = None
        coveredTo: IsoTime | None = None
        note: I18n | None = None


@router.get("/closures/{closure_id}/live", response_model=LiveCheck, response_model_by_alias=True)
def closure_live(closure_id: str):
    return LiveCheck.model_validate(compute_live_check(closure_id))


@router.get("/closures/{closure_id}/reports", response_model=ReportSummary, response_model_by_alias=True)
def closure_reports(closure_id: str,
                    radius: float = Query(500.0, description="metres around the closure, 1-5000")):
    return ReportSummary.model_validate(report_summary(closure_id, radius))
