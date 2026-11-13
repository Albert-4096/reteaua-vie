"""The M7 endpoints through the app: contract shapes, content types, errors."""

from __future__ import annotations

from app.models.v2 import ComplianceReport, ExportFile, HistoryEntry, IndicatorSet
from tests.conftest import needs_data

PATHS = ("/api/feed/datex.xml", "/api/compliance", "/api/history", "/api/indicators", "/api/exports",
         "/api/exports/nap-metadata.json")


def test_router_is_mounted():
    from app import main

    assert "app.m7_compliance.api_m7" in main.ROUTER_MODULES
    from app.m7_compliance.exports import mounted_paths

    assert set(PATHS) <= mounted_paths()


@needs_data
def test_compliance_and_exports(client):
    r = client.get("/api/compliance")
    assert r.status_code == 200
    rep = ComplianceReport.model_validate(r.json())
    assert {o.id: o.status for o in rep.obligations}["RTTI"] == "covered"   # datex.xml is served
    files = [ExportFile.model_validate(x) for x in client.get("/api/exports").json()]
    names = [f.name for f in files]
    assert {"alerts.pb", "datex.xml", "history.json", "nap-metadata.json"} <= set(names)
    for o in rep.obligations:
        assert set(o.coveredBy) <= set(names)


@needs_data
def test_nap_metadata_is_json_ld(client):
    r = client.get("/api/exports/nap-metadata.json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/ld+json")
    assert r.json()["@type"] == "dcat:Catalog"


@needs_data
def test_history_and_indicators(client):
    r = client.get("/api/history", params={"from": "2026-11-01", "to": "2026-11-30"})
    assert r.status_code == 200
    rows = r.json()
    # E3 (notice 11065): back-filled, or the platform row once precompute published it (T4)
    assert any(x["closureId"] in ("stpt_11065", "cl_20261107_e3") for x in rows)
    for x in rows:
        HistoryEntry.model_validate({k: v for k, v in x.items() if k not in ("note", "sourceUrl", "provenance")})
    assert client.get("/api/history", params={"from": "nope"}).status_code == 422
    r = client.get("/api/indicators")
    assert r.status_code == 200
    IndicatorSet.model_validate(r.json())


@needs_data
def test_datex_endpoint(client):
    r = client.get("/api/feed/datex.xml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    assert b"SituationPublication" in r.content


def test_warm_hook_exists():
    from app.m7_compliance import warm

    assert callable(warm.warm)
