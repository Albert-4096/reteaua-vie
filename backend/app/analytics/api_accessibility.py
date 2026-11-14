"""R6: GET /api/accessibility/lines, /api/accessibility/stops/{stopId}, /api/layers/accessibility."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.analytics import accessibility as acc
from app.analytics.models import AccessibilityLines, StopAccessibility
from app.common.errors import ApiError, not_found
from app.models.v2 import LayerCollection

router = APIRouter(tags=["R6 accessibility"])


def _parse_bbox(bbox: str | None):
    from app.overview.api_layers import parse_bbox
    return parse_bbox(bbox)


@router.get("/accessibility/lines", response_model=AccessibilityLines, response_model_by_alias=True)
def get_lines() -> dict:
    return acc.lines_report()


@router.get("/accessibility/stops/{stop_id}", response_model=StopAccessibility, response_model_by_alias=True)
def get_stop(stop_id: str) -> dict:
    d = acc.stop_report(stop_id)
    if d is None:
        raise not_found(f"No stop {stop_id!r} in the feed in force.", "NO_SUCH_STOP")
    return d


@router.get("/layers/accessibility", response_model=LayerCollection)
def get_layer(bbox: str | None = Query(None, description="minLon,minLat,maxLon,maxLat")) -> dict:
    return acc.layer(_parse_bbox(bbox))
