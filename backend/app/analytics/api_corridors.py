"""A8: GET /api/corridors."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.analytics import corridors
from app.analytics.models import CorridorsResponse

router = APIRouter(tags=["A8 corridors"])


@router.get("/corridors", response_model=CorridorsResponse)
def get_corridors(day: str = Query("weekday", description="weekday | saturday | sunday"),
                  routeId: str | None = Query(None, description="only corridors this line runs on"),
                  minStops: int = Query(corridors.MIN_STOPS, ge=2, le=20),
                  onlyProposals: bool = Query(False), limit: int = Query(50, ge=1, le=500)) -> dict:
    return corridors.corridors(day, routeId, minStops, onlyProposals, limit)
