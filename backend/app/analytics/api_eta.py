"""A13: GET /api/feed/tripupdates.pb, /api/feed/tripupdates.json and /api/eta/backtest."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from app.analytics import eta
from app.analytics.models import EtaBacktest, EtaDebug
from app.common.errors import ApiError

router = APIRouter(tags=["A13 ETA"])


@router.get("/feed/tripupdates.pb", response_class=Response,
            responses={200: {"content": {"application/x-protobuf": {}}, "description": "GTFS Realtime 2.0 TripUpdates (estimate)"}})
def tripupdates_pb() -> Response:
    return Response(eta.feed_bytes(eta.build()), media_type="application/x-protobuf",
                    headers={"Cache-Control": "no-cache", "Content-Disposition": 'inline; filename="tripupdates.pb"'})


@router.get("/feed/tripupdates.json", response_model=EtaDebug, response_model_by_alias=True)
def tripupdates_json() -> dict:
    return eta.debug(eta.build())


@router.get("/eta/backtest", response_model=EtaBacktest, response_model_by_alias=True)
def get_backtest() -> dict:
    try:
        return eta.backtest()
    except RuntimeError as e:
        raise ApiError(404, "NOT_READY", f"{e}")
