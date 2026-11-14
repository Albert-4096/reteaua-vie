"""GET /api/live/missing?from=&to= | ?case=case_l23: lines with no vehicle in our live recording (O2).

Reads only our recording and the GTFS in force; never a call to the city.
Default window: the last 60 min of the real clock (not the demo clock).
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.common.errors import invalid
from app.common.timeutil import parse_iso
from app.live import missing
from app.models.live_missing import MissingLines

router = APIRouter(tags=["live"])


def _time(value: str, name: str):
    try:
        return parse_iso(value.strip().replace(" ", "+"))  # an unencoded '+' arrives as a space
    except ValueError:
        raise invalid(f"`{name}` must be an ISO 8601 time, e.g. 2026-11-14T06:00:00+02:00")


@router.get("/live/missing", response_model=MissingLines)
def live_missing(
    from_: str | None = Query(None, alias="from", description="ISO time; default `to` minus 60 min"),
    to: str | None = Query(None, description="ISO time; default the real clock"),
    case: str | None = Query(None, description="prepared case, e.g. case_l23 (ignores from/to)"),
) -> dict:
    if case:
        if case not in missing.CASES:
            raise invalid(f"`case` must be one of {', '.join(missing.CASES)}")
        return missing.prepared(case)
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
    return missing.detect(start, end)
