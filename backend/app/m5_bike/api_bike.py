"""GET /api/closures/{id}/bike: BikeImpact (M5, SPEC §6.5). Synchronous, < 1 s once warm."""

from __future__ import annotations

from fastapi import APIRouter

from app.m5_bike import bike
from app.m5_bike.warm import warm_in_background
from app.models.v2 import BikeImpact

router = APIRouter(tags=["M5 bike"])

warm_in_background()


@router.get("/closures/{closure_id}/bike", response_model=BikeImpact)
def get_bike(closure_id: str) -> BikeImpact:
    return bike.bike_impact(closure_id)
