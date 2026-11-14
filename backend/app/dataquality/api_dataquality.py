"""R12 endpoints: the data-quality sheet and its CSV (CONTRACT v2.16)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from app.dataquality import checks
from app.dataquality.models import DataQuality

router = APIRouter(tags=["R12 data quality"])


@router.get("/data-quality", response_model=DataQuality)
def data_quality() -> DataQuality:
    return checks.data_quality()


@router.get("/data-quality.csv")
def data_quality_csv() -> Response:
    body = checks.to_csv(checks.data_quality())
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="calitatea-datelor.csv"'})
