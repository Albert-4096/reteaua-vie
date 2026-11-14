"""R11 endpoints: paid parking in the works window (CONTRACT v2.28)."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.m6_parking import paid
from app.models.v2 import PaidParking

router = APIRouter(tags=["R11 paid parking"])

START = Query(None, description="ISO time with offset; default: the closure window start")
END = Query(None, description="ISO time with offset; default: the closure window end")


@router.get("/closures/{closure_id}/paid-parking", response_model=PaidParking)
def get_paid_parking(closure_id: str, start: str | None = START, end: str | None = END) -> PaidParking:
    return paid.paid_parking(closure_id, start, end)


@router.get("/closures/{closure_id}/paid-parking.csv")
def get_paid_parking_csv(closure_id: str, start: str | None = START, end: str | None = END) -> Response:
    return Response(paid.to_csv(closure_id, start, end), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="lista-timpark.csv"'})
