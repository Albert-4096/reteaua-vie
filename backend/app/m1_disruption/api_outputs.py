"""M1 outputs: publish, the GTFS-RT alert feed, its validation and the stop poster.

    POST /api/closures/{id}/publish          PublishResult (409 UNCONFIRMED / NOT_ANALYZED)
    GET  /api/feed/alerts.pb                 GTFS-RT FeedMessage, every published alert
    GET  /api/feed/alerts.json               the same alerts as Alert[]
    GET  /api/closures/{id}/validation       FeedValidation for the „validator pe ecran” panel
    GET  /api/closures/{id}/poster.pdf?stopId=   A4 poster for one affected stop
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.common.errors import not_found
from app.m1_disruption import poster as poster_mod
from app.m1_disruption import publish as publish_mod
from app.m1_disruption.alerts import FeedValidation
from app.models.v1 import Alert, PublishResult

router = APIRouter(tags=["M1 outputs"])

_ID = re.compile(r"^[A-Za-z0-9_-]{1,120}$")


def _check_id(closure_id: str) -> str:
    if not _ID.match(closure_id):
        raise not_found(f"No closure {closure_id!r}.")
    return closure_id


@router.post("/closures/{closure_id}/publish", response_model=PublishResult)
def publish_closure(closure_id: str) -> PublishResult:
    """Publish the closure's alerts. Refused (409 UNCONFIRMED) while an unsure stop has no decision."""
    return publish_mod.publish(_check_id(closure_id))


@router.get("/feed/alerts.pb", response_class=Response,
            responses={200: {"content": {"application/x-protobuf": {}},
                             "description": "GTFS Realtime 2.0 FeedMessage (FULL_DATASET)"}})
def alerts_pb() -> Response:
    return Response(content=publish_mod.feed_bytes(), media_type="application/x-protobuf",
                    headers={"Cache-Control": "no-cache",
                             "Content-Disposition": 'inline; filename="alerts.pb"'})


@router.get("/feed/alerts.json", response_model=list[Alert])
def alerts_json() -> list[Alert]:
    return publish_mod.published_alerts()


@router.get("/closures/{closure_id}/validation", response_model=FeedValidation)
def feed_validation(closure_id: str) -> FeedValidation:
    """The GTFS-RT validator result for the feed right after this closure was published."""
    return publish_mod.get_validation(_check_id(closure_id))


@router.get("/closures/{closure_id}/poster.pdf", response_class=Response,
            responses={200: {"content": {"application/pdf": {}}, "description": "A4 portrait PDF"}})
def poster_pdf(closure_id: str, stopId: str = Query(..., min_length=1, max_length=40)) -> Response:  # noqa: N803
    pdf = poster_mod.poster_pdf(_check_id(closure_id), stopId)
    safe_stop = re.sub(r"[^A-Za-z0-9_-]", "_", stopId)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="afis_{closure_id}_{safe_stop}.pdf"'})
