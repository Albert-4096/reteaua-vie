"""R27: GET /api/closures/{closureId}/timetable-check?date="""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from app.cityapp import timetable_check
from app.common.errors import invalid

router = APIRouter(tags=["R27 City Hall timetable check"])


@router.get("/closures/{closure_id}/timetable-check")
def get_timetable_check(closure_id: str, date_: str | None = Query(None, alias="date", description="YYYY-MM-DD, default today")) -> dict:
    try:
        day = date.fromisoformat(date_) if date_ else None
    except ValueError:
        raise invalid("`date` must be YYYY-MM-DD") from None
    return timetable_check.check(closure_id, day)
