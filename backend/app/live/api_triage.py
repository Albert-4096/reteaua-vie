"""R4: PATCH /api/live/missing/{routeId} (a person's decision on an O2 row) and
GET /api/live/missing/log.csv?month= (the month's decisions, for SMTT)."""

from __future__ import annotations

import re

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.common.errors import invalid
from app.config import real_now
from app.live import triage
from app.models.live_missing import TriageDecision, TriageInput

router = APIRouter(tags=["live"])


@router.patch("/live/missing/{routeId}", response_model=TriageDecision)
def decide(routeId: str, body: TriageInput) -> dict:
    return triage.record(routeId, body.model_dump())


@router.get("/live/missing/log.csv")
def log_csv(month: str | None = Query(None, description="YYYY-MM, the month of the rows' windows; default this month")):
    month = month or real_now().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise invalid("`month` must be YYYY-MM, e.g. 2026-11")
    return Response(triage.log_csv(month), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="linii-fara-vehicul-{month}.csv"'})
