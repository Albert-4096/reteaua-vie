"""A10: GET /api/coverage/zones and /api/layers/coverage."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.analytics import coverage
from app.analytics.models import CoverageSummary
from app.models.v2 import LayerCollection

router = APIRouter(tags=["A10 coverage"])


@router.get("/coverage/zones", response_model=CoverageSummary)
def get_zones(day: str = Query("weekday", description="weekday | saturday | sunday"),
              from_: int = Query(coverage.HOURS[0], alias="from", ge=0, le=23),
              to: int = Query(coverage.HOURS[1], ge=1, le=24)) -> dict:
    return coverage.summary(day, from_, to)


@router.get("/layers/coverage", response_model=LayerCollection)
def get_layer(day: str = Query("weekday"), from_: int = Query(coverage.HOURS[0], alias="from", ge=0, le=23),
              to: int = Query(coverage.HOURS[1], ge=1, le=24)) -> dict:
    return coverage.layer(day, from_, to)
