"""R8 + L4: GET /api/streets/critical, /api/layers/streets, /api/standing."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.analytics import streets
from app.analytics.models import CriticalStreetsResponse, StandingResponse
from app.common.errors import ApiError
from app.models.v2 import LayerCollection

router = APIRouter(tags=["R8 critical streets, L4 standing"])


def _guard(fn, *a):
    try:
        return fn(*a)
    except RuntimeError as e:
        raise ApiError(404, "NOT_READY", f"{e}")


@router.get("/streets/critical", response_model=CriticalStreetsResponse)
def get_critical(limit: int = Query(15, ge=1, le=2000, description="sections returned, most minutes lost first")) -> dict:
    d = _guard(streets.critical_streets)
    return {**d, "sections": [{k: v for k, v in s.items() if not k.startswith("_")} for s in d["sections"][:limit]]}


@router.get("/layers/streets", response_model=LayerCollection)
def get_layer(limit: int = Query(300, ge=1, le=2000)) -> dict:
    return _guard(streets.layer, limit)


@router.get("/standing", response_model=StandingResponse)
def get_standing(limit: int = Query(30, ge=1, le=300)) -> dict:
    d = _guard(streets.standing)
    return {**d, "points": d["points"][:limit]}
