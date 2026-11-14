"""C1: POST /api/checkin, GET /api/checkins?routeId=&from=&to="""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Query

from app.checkin import service
from app.checkin.models import CheckinAck, CheckinCounts, CheckinInput
from app.common.errors import invalid
from app.common.timeutil import parse_iso
from app.config import real_now

router = APIRouter(tags=["C1 check-in"])


@router.post("/checkin", response_model=CheckinAck)
def post_checkin(body: CheckinInput) -> CheckinAck:
    return service.accept(body)


def _t(v: str, name: str):
    try:
        return parse_iso(v.strip().replace(" ", "+"))
    except ValueError:
        raise invalid(f"`{name}` must be an ISO 8601 time") from None


@router.get("/checkins", response_model=CheckinCounts)
def get_checkins(routeId: str | None = None,
                 from_: str | None = Query(None, alias="from", description="ISO time; default `to` minus 24 h"),
                 to: str | None = Query(None, description="ISO time; default now")) -> CheckinCounts:
    end = _t(to, "to") if to else real_now()
    start = _t(from_, "from") if from_ else end - timedelta(hours=24)
    if start >= end:
        raise invalid("`from` must be before `to`")
    return service.counts(start, end, routeId)


@router.get("/checkins/confirmations")
def get_confirmations(from_: str = Query(..., alias="from"), to: str = Query(...)) -> dict:
    """C2 on its own: {routeId: ServiceConfirmation} for check-ins in the window (the same data
    /api/live/missing rows carry as `serviceConfirmation`)."""
    from app.checkin import confirm
    start, end = _t(from_, "from"), _t(to, "to")
    if start >= end:
        raise invalid("`from` must be before `to`")
    return {r: c.model_dump() for r, c in confirm.confirmations(start, end).items()}
