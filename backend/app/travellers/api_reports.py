"""R20: POST /api/problem-report and GET /api/problem-reports (fixed categories, counts only).

Our own rider signal with the check-in's privacy model; it never writes to the City Hall's Sesizări (the poster
also links to the official app, that link is frontend; the official count since publish is `since` on
GET /api/closures/{id}/reports). A signal, never a fact."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Query

from app.common.errors import invalid
from app.common.timeutil import parse_iso
from app.config import real_now
from app.travellers import service
from app.travellers.models import ReportAck, ReportInput, ReportSummary

router = APIRouter(tags=["R20 traveller reports"])


@router.post("/problem-report", response_model=ReportAck)
def post_report(body: ReportInput) -> ReportAck:
    return service.accept(body)


@router.get("/problem-reports", response_model=ReportSummary)
def get_reports(stopId: str | None = None, routeId: str | None = None,
                from_: str | None = Query(None, alias="from"), to: str | None = None) -> ReportSummary:
    try:
        end = parse_iso(to.strip().replace(" ", "+")) if to else real_now()
        start = parse_iso(from_.strip().replace(" ", "+")) if from_ else end - timedelta(hours=24)
    except ValueError:
        raise invalid("`from` and `to` must be ISO 8601 times") from None
    if start >= end:
        raise invalid("`from` must be before `to`")
    return service.summary(start, end, stopId, routeId)
