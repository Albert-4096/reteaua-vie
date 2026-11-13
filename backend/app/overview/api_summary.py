"""GET /api/overview?at=: the step 0 KPI strip (SPEC §6.10), default at the demo clock."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.common.errors import invalid
from app.common.timeutil import parse_iso
from app.models.v2 import Overview
from app.overview.summary import overview

router = APIRouter(tags=["overview"])


@router.get("/overview", response_model=Overview)
def get_overview(at: str | None = Query(None, description="ISO time; default DEMO_NOW or now")) -> Overview:
    when = None
    if at:
        try:
            when = parse_iso(at.strip().replace(" ", "+"))  # an unencoded '+' arrives as a space
        except ValueError:
            raise invalid("`at` must be an ISO 8601 time, e.g. 2026-11-08T12:00:00+02:00")
    return Overview.model_validate(overview(when))
