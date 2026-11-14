"""R14: GET /api/registry?from=&to=&verify="""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from app.common.errors import invalid
from app.registry import daily

router = APIRouter(tags=["R14 registry"])


@router.get("/registry")
def get_registry(from_: str | None = Query(None, alias="from", description="YYYY-MM-DD; default the first recorded day"),
                 to: str | None = Query(None, description="YYYY-MM-DD; default the last recorded day"),
                 verify: int = Query(0, ge=0, le=1)) -> dict:
    days = daily.recorded_days()
    try:
        start = date.fromisoformat(from_) if from_ else (days[0] if days else date.today())
        end = date.fromisoformat(to) if to else (days[-1] if days else date.today())
    except ValueError:
        raise invalid("`from` and `to` must be YYYY-MM-DD") from None
    if start > end:
        raise invalid("`from` must not be after `to`")
    return daily.registry(start, end, bool(verify))
