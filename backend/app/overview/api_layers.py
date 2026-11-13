"""GET /api/layers/parking: Timpark zones, streets and lots (city ids and colours)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.common.city import parking_layer
from app.common.errors import invalid
from app.models.v2 import LayerCollection

router = APIRouter(tags=["layers"])


def parse_bbox(bbox: str | None) -> tuple[float, float, float, float] | None:
    """`minLon,minLat,maxLon,maxLat` -> tuple, or None."""
    if not bbox:
        return None
    try:
        parts = tuple(float(x) for x in bbox.split(","))
    except ValueError:
        parts = ()
    if len(parts) != 4 or parts[0] >= parts[2] or parts[1] >= parts[3]:
        raise invalid("`bbox` must be minLon,minLat,maxLon,maxLat")
    return parts  # type: ignore[return-value]


@router.get("/layers/parking", response_model=LayerCollection)
def layer_parking(bbox: str | None = Query(None, description="minLon,minLat,maxLon,maxLat")) -> dict:
    return parking_layer(parse_bbox(bbox))
