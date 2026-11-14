"""R26 + R19 endpoints (CONTRACT v2.19, v2.20)."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.city_reports import core
from app.city_reports.models import AreaReports, RoadIssues
from app.models.v2 import LayerCollection

router = APIRouter(tags=["R26 R19 sesizari"])

CAT = Query(None, description="all (default) or one of: Transport în comun, Trafic rutier și semne de circulație, Străzi și trotuare")


@router.get("/reports/zones", response_model=AreaReports)
def zones(category: str | None = CAT) -> AreaReports:
    return core.by_zone(category)


@router.get("/reports/zones.csv")
def zones_csv(category: str | None = CAT) -> Response:
    return Response(core.to_csv(core.by_zone(category)), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="sesizari-zone.csv"'})


@router.get("/reports/stops", response_model=AreaReports)
def stops(category: str | None = CAT, radius: int = Query(core.STOP_RADIUS_M, description="metres, 5-300"),
          limit: int = Query(50, ge=1, le=500)) -> AreaReports:
    return core.by_stop(category, radius, limit)


@router.get("/reports/stops.csv")
def stops_csv(category: str | None = CAT, radius: int = Query(core.STOP_RADIUS_M), limit: int = Query(500, ge=1, le=500)) -> Response:
    return Response(core.to_csv(core.by_stop(category, radius, limit)), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="sesizari-statii.csv"'})


@router.get("/road-issues", response_model=RoadIssues)
def road_issues(limit: int = Query(5, ge=1, le=200)) -> RoadIssues:
    return core.road_segments(limit)[0]


@router.get("/layers/road_issues", response_model=LayerCollection)
def road_issues_layer() -> dict:
    summary, feats = core.road_segments(1)
    return {"type": "FeatureCollection", "layer": "road_issues", "features": feats,
            "provenance": [p.model_dump() for p in summary.provenance]}
