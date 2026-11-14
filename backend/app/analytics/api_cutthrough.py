"""R23: GET /api/closures/{id}/cut-through, /api/feed/waze-cifs.json, /api/feed/avoid-streets.geojson."""

from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from app.analytics import cutthrough, navfeed
from app.analytics.models import CutThrough
from app.common.jobs import respond

router = APIRouter(tags=["R23 cut-through"])


@router.get("/closures/{closure_id}/cut-through", response_model=CutThrough,
            responses={202: {"description": "Job started: poll /api/jobs/{jobId}"}})
def get_cut_through(closure_id: str):
    cutthrough.closure_or_404(closure_id)
    return respond(cutthrough.job_key(closure_id), lambda: cutthrough.build(closure_id))


def _file(doc: dict, notes: list[str], media: str) -> Response:
    headers = {"X-Notes": "; ".join(notes)[:900]} if notes else {}
    return Response(json.dumps(doc, ensure_ascii=False), media_type=media, headers=headers)


@router.get("/feed/waze-cifs.json", response_class=Response)
def waze_cifs() -> Response:
    return _file(*navfeed.cifs(), "application/json")


@router.get("/feed/avoid-streets.geojson", response_class=Response)
def avoid_streets() -> Response:
    return _file(*navfeed.avoid_streets(), "application/geo+json")


# R24 lives here too: one module of closure-level analytics endpoints.
from app.analytics import balance  # noqa: E402
from app.analytics.models import WorksBalance  # noqa: E402


@router.get("/closures/{closure_id}/balance", response_model=WorksBalance, response_model_by_alias=True,
            responses={202: {"description": "Job started: poll /api/jobs/{jobId}"}})
def get_balance(closure_id: str):
    cutthrough.closure_or_404(closure_id)
    return respond(balance.job_key(closure_id), lambda: WorksBalance.model_validate(balance.balance(closure_id)))
