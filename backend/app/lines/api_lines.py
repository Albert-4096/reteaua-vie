"""R2: GET /api/lines/status?at=&routeId=&since= (one state per line, for CityApp and Timi)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.common.errors import invalid
from app.common.timeutil import parse_iso
from app.config import now
from app.lines.status import lines_status
from app.models.lines_status import LinesStatus

router = APIRouter(tags=["R2 line status"])


def _time(value: str, name: str):
    try:
        return parse_iso(value.strip().replace(" ", "+"))  # an unencoded '+' arrives as a space
    except ValueError:
        raise invalid(f"`{name}` must be an ISO 8601 time, e.g. 2026-11-08T12:00:00+02:00")


@router.get("/lines/status", response_model=LinesStatus)
def get_lines_status(
    at: str | None = Query(None, description="ISO time; default DEMO_NOW or now"),
    routeId: str | None = Query(None, description="one GTFS route, e.g. R_TV_4 (plus its temporary lines)"),
    since: str | None = Query(None, description="ISO time; only the lines whose state changed since then"),
) -> dict:
    when = _time(at, "at") if at else now()
    before = _time(since, "since") if since else None
    if before is not None and before > when:
        raise invalid("`since` must be before `at`")
    return lines_status(when, routeId or None, before)
