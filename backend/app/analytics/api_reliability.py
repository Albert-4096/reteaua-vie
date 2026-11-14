"""L3: GET /api/reliability/lines and /api/reliability/vehicles (measured from the recording, via L0)."""

from __future__ import annotations

from fastapi import APIRouter

from app.analytics import gps_health, reliability
from app.analytics.models import ReliabilityResponse, VehicleHealthResponse
from app.common.errors import ApiError

router = APIRouter(tags=["L3 reliability"])


def _not_ready(e: RuntimeError) -> ApiError:
    return ApiError(404, "NOT_READY", f"{e}")


@router.get("/reliability/lines", response_model=ReliabilityResponse, response_model_by_alias=True)
def get_lines() -> dict:
    try:
        return reliability.report()
    except RuntimeError as e:
        raise _not_ready(e)


@router.get("/reliability/vehicles", response_model=VehicleHealthResponse, response_model_by_alias=True)
def get_vehicles() -> dict:
    try:
        return gps_health.report()
    except RuntimeError as e:
        raise _not_ready(e)
