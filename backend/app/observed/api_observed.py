"""GET /api/observed/summary: the observed timetable (L0) built from our vehicle recording.

Reads only what app.observed.build wrote; a request never parses the raw recording. When hours
are ready to build, a background thread builds them, so the summary follows the recording.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.observed import build, summary
from app.observed.models import ObservedSummary

router = APIRouter(tags=["L0 observed timetable"])


@router.get("/observed/summary", response_model=ObservedSummary, response_model_by_alias=True)
def get_observed_summary() -> ObservedSummary:
    build.build_in_background()
    return summary.summary()
