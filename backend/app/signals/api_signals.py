"""R9: GET /api/signals/waits and GET /api/closures/{id}/signals."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.common.jobs import respond
from app.signals import waits
from app.signals.waits import DetourSignals, SignalWaits

router = APIRouter(tags=["R9 signals"])


@router.get("/signals/waits", response_model=SignalWaits)
def get_waits(limit: int = Query(30, ge=1, le=300)) -> SignalWaits:
    try:
        return waits.ranking(limit)
    except RuntimeError:     # L0 has no built hour yet
        from app.common.errors import unavailable
        raise unavailable("În lucru: înregistrarea nu e încă procesată.", code="IN_LUCRU")


@router.get("/closures/{closure_id}/signals", response_model=DetourSignals,
            responses={202: {"description": "Job started: poll /api/jobs/{jobId}"}})
def get_detour_signals(closure_id: str):
    from app.observed import window_cost
    from app.m4_access import windows as win
    win.load_closure(closure_id)
    key = f"detour-signals:v1:{closure_id}:{window_cost.closure_fingerprint(closure_id)}"
    return respond(key, lambda: waits.on_detour(closure_id))

