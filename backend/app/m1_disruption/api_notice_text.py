"""GET /api/closures/{id}/notice: the public notice generated from a closure (D-013).

Thin router over notice_text.build_notice; mounted under /api by app.main.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.common import state
from app.common.errors import not_found
from app.m1_disruption import analysis as an
from app.m1_disruption import impact as imp
from app.m1_disruption.notice_text import GeneratedNotice, build_notice

router = APIRouter(tags=["M1 notice"])


@router.get("/closures/{closure_id}/notice", response_model=GeneratedNotice)
def get_notice(closure_id: str) -> GeneratedNotice:
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id}.")
    analysis = an.get_analysis(closure_id)
    if analysis is None:
        raise not_found(f"Closure {closure_id} was never analyzed.", code="NOT_ANALYZED")
    return build_notice(closure, analysis, imp.compute_impact(closure_id))
