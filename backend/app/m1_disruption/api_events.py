"""N2 endpoint: events inside the works window (CONTRACT v2.18)."""

from __future__ import annotations

from fastapi import APIRouter

from app.m1_disruption import events

router = APIRouter(tags=["N2 events"])


@router.get("/closures/{closure_id}/events", response_model=events.EventConflicts)
def get_events(closure_id: str) -> events.EventConflicts:
    return events.events_for(closure_id)
