"""M6 endpoint: Timpark streets and lots in the closure buffer, Park & Ride options."""

from __future__ import annotations

from fastapi import APIRouter

from app.m6_parking import parking
from app.models.v2 import ParkingImpact

router = APIRouter(tags=["M6 parking"])

# GTFS stop patterns, OSM names and the P&R list load in the background, so the first request is fast
parking.warm_in_background()


@router.get("/closures/{closure_id}/parking", response_model=ParkingImpact)
def get_parking(closure_id: str) -> ParkingImpact:
    return parking.parking_impact(closure_id)
