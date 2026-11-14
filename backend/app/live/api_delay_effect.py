"""R25: GET /api/closures/{closure_id}/delay-effect (the delay a closure's diversion adds, measured)."""

from __future__ import annotations

from fastapi import APIRouter

from app.live.delay_effect import closure_delay_effect
from app.models.delay_effect import ClosureDelayEffect

router = APIRouter(tags=["live"])


@router.get("/closures/{closure_id}/delay-effect", response_model=ClosureDelayEffect)
def delay_effect(closure_id: str) -> dict:
    return closure_delay_effect(closure_id)
