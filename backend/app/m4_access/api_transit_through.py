"""R10 endpoint: the bus keeps one lane through the works (CONTRACT v2.36)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.m4_access import transit_through as tt
from app.models.v2 import TransitThrough

router = APIRouter(tags=["R10 transit through"])


@router.get("/closures/{closure_id}/transit-through", response_model=TransitThrough)
def get_transit_through(closure_id: str,
                        routeIds: str | None = Query(None, description="comma list of routeIds; default: every bus and trolleybus line in the closure"),
                        lanesConfirmed: bool = Query(False, description="a person confirmed the lane: skip the OSM judgement")) -> TransitThrough:
    ids = [x.strip() for x in routeIds.split(",") if x.strip()] if routeIds else []
    return tt.transit_through(closure_id, ids, lanesConfirmed)
