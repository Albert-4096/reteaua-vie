"""R28 endpoint: landmarks that lose their nearest stop (CONTRACT v2.27)."""

from __future__ import annotations

from fastapi import APIRouter

from app.m4_access import landmarks
from app.models.v2 import LandmarkImpact

router = APIRouter(tags=["R28 landmarks"])


@router.get("/closures/{closure_id}/landmarks", response_model=LandmarkImpact)
def get_landmarks(closure_id: str) -> LandmarkImpact:
    return landmarks.landmark_impact(closure_id)
