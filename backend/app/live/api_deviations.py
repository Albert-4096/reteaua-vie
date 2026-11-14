"""R18: GET /api/live/deviations?from=&to= (off-route runs in our recording, with or without a notice).

Default window: the last 60 min of the real clock (not the demo clock: no recording on 8 Nov).
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.common.errors import invalid
from app.common.timeutil import parse_iso
from app.live import deviations, missing
from app.models.live_deviations import Deviations

router = APIRouter(tags=["live"])


def _time(value: str, name: str):
    try:
        return parse_iso(value.strip().replace(" ", "+"))  # an unencoded '+' arrives as a space
    except ValueError:
        raise invalid(f"`{name}` must be an ISO 8601 time, e.g. 2026-11-14T06:00:00+02:00")


@router.get("/live/deviations", response_model=Deviations)
def live_deviations(
    from_: str | None = Query(None, alias="from", description="ISO time; default `to` minus 60 min"),
    to: str | None = Query(None, description="ISO time; default the real clock"),
) -> dict:
    start, end = missing.live_window()
    if to:
        end = _time(to, "to")
        start = end - missing.DEFAULT_WINDOW
    if from_:
        start = _time(from_, "from")
    if start >= end:
        raise invalid("`from` must be before `to`")
    if end - start > missing.MAX_WINDOW:
        raise invalid("the window may be at most 24 h")
    return deviations.detect(start, end)
