"""GET /api/live/vehicles?routeId=: the newest snapshot of our recording.

Never a call to the city: the recorder polls every 15 s; we serve its newest
complete line. On the demo clock the frontend still gets the newest recording,
with its real time in provenance (SPEC §6.10).
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.common.vehicles import vehicles_layer
from app.models.v2 import LayerCollection

router = APIRouter(tags=["live"])


@router.get("/live/vehicles", response_model=LayerCollection)
def live_vehicles(routeId: str | None = Query(None, description="City route id, e.g. R_TV_4")) -> dict:
    return vehicles_layer(routeId)
