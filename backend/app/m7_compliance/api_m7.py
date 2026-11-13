"""M7: EU compliance, disruption history, indicators, exports, NAP metadata, DATEX II.

    GET /api/feed/datex.xml                 DATEX II v3 SituationPublication of every published closure
    GET /api/feed/alerts.ngsi.json          NGSI-LD: FIWARE Alert + GtfsStop entities of the published alerts
    GET /api/compliance                     ComplianceReport (statuses describe our exports only)
    GET /api/history?from=&to=              HistoryEntry[] (platform + back-filled from STPT notices)
    GET /api/indicators                     IndicatorSet (PMUD / TEN-T, each with its method)
    GET /api/exports                        ExportFile[]: every file we publish
    GET /api/exports/nap-metadata.json      mobilityDCAT-AP JSON-LD dcat:Catalog
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response

from app.m7_compliance import compliance as compliance_mod
from app.m7_compliance import datex as datex_mod
from app.m7_compliance import exports as exports_mod
from app.m7_compliance import history as history_mod
from app.m7_compliance import indicators as indicators_mod
from app.m7_compliance import ngsi as ngsi_mod
from app.models.v2 import ComplianceReport, ExportFile, IndicatorSet

router = APIRouter(tags=["M7 compliance and exports"])


@router.get("/feed/datex.xml", response_class=Response,
            responses={200: {"content": {"application/xml": {}},
                             "description": "DATEX II v3.5 d2:payload, xsi:type sit:SituationPublication"}})
def datex_xml() -> Response:
    return Response(content=datex_mod.feed_xml(), media_type="application/xml",
                    headers={"Cache-Control": "no-cache", "Content-Disposition": 'inline; filename="datex.xml"'})


@router.get("/feed/alerts.ngsi.json", response_class=JSONResponse,
            responses={200: {"content": {"application/ld+json": {}},
                             "description": "NGSI-LD entities (normalized): FIWARE Smart Data Models Alert and "
                                            "GtfsStop; GeoJSON coordinates [lon, lat]; times UTC"}})
def alerts_ngsi() -> JSONResponse:
    return JSONResponse(content=ngsi_mod.entities(), media_type=ngsi_mod.MEDIA_TYPE,
                        headers={"Cache-Control": "no-cache"})


@router.get("/compliance", response_model=ComplianceReport)
def compliance() -> ComplianceReport:
    return compliance_mod.report(exports_mod.mounted_paths())


@router.get("/history", response_model=list[history_mod.HistoryRow], response_model_exclude_none=False)
def history(date_from: str | None = Query(None, alias="from", max_length=40),
            date_to: str | None = Query(None, alias="to", max_length=40)) -> list[history_mod.HistoryRow]:
    """Published closures and STPT notices reconstructed as history (`note` labels the reconstructed ones)."""
    return history_mod.history(date_from, date_to)


@router.get("/indicators", response_model=IndicatorSet)
def indicators() -> IndicatorSet:
    return indicators_mod.indicators()


@router.get("/exports", response_model=list[ExportFile])
def exports() -> list[ExportFile]:
    return exports_mod.export_files(exports_mod.mounted_paths())


@router.get("/exports/nap-metadata.json", response_class=JSONResponse,
            responses={200: {"content": {"application/ld+json": {}},
                             "description": "mobilityDCAT-AP dcat:Catalog (JSON-LD)"}})
def nap_metadata() -> JSONResponse:
    return JSONResponse(content=exports_mod.nap_metadata(exports_mod.mounted_paths()),
                        media_type="application/ld+json")
