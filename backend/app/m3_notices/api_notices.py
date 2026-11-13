"""M3 endpoints: neighbourhood notices of a closure and the feed CityApp would read."""

from __future__ import annotations

from fastapi import APIRouter

from app.m3_notices import notices
from app.models.v2 import ZoneNotice

router = APIRouter(tags=["M3 notices"])


@router.get("/closures/{closure_id}/notices", response_model=list[ZoneNotice])
def get_notices(closure_id: str) -> list[ZoneNotice]:
    """One notice per neighbourhood hit; publishedAt is null until the closure is published."""
    return notices.notices_for(closure_id)


@router.get("/feed/notices.json", response_model=list[ZoneNotice])
def get_feed() -> list[ZoneNotice]:
    """Notices of every published closure whose window has not ended (demo clock)."""
    return notices.feed()
