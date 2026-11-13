"""Sesizări around a closure (SPEC §6.9): aggregate counts only, on the real recording."""

from __future__ import annotations

import json
import warnings

import pytest

from app.live import reports
from tests.conftest import DATA_DIR, needs_data

HAS_SESIZARI = any((DATA_DIR / "live" / "sesizari").glob("*.json"))
HAS_CASES = (DATA_DIR / "state" / "closures" / "cl_20261102_mocioni.json").is_file()
needs_sesizari = pytest.mark.skipif(not (HAS_SESIZARI and HAS_CASES), reason="no sesizări recording or cases")

# The status values seen in sesizari.primariatm.ro on 11-13 Nov 2026. Only "Finalizata" means resolved.
KNOWN_STATUSES = {"Inregistrata", "In lucru", "Asteapta clarificari", "Declinata competenta", "Finalizata"}


@needs_sesizari
def test_real_status_values():
    values = set(reports.status_values())
    assert "Finalizata" in values and reports.RESOLVED <= KNOWN_STATUSES
    new = values - KNOWN_STATUSES
    if new:  # a new status must be classified (resolved or not) by a person
        warnings.warn(f"new sesizări status values: {sorted(new)}")
    print("sesizări status values:", sorted(values))


@needs_sesizari
def test_deduplicated_by_id():
    ids = set()
    rows = 0
    for p in (DATA_DIR / "live" / "sesizari").glob("*.json"):
        data = json.loads(p.read_text(encoding="utf-8"))
        rows += len(data)
        ids |= {str(r["id"]) for r in data if (r.get("locatie") or {}).get("coordinates")}
    assert set(reports.load_reports()) == ids
    assert len(ids) < rows  # the 2-day polls overlap


@needs_data
@needs_sesizari
def test_mocioni_counts_without_personal_data():
    r = reports.report_summary("cl_20261102_mocioni", 500)
    assert r["total"] is not None and r["total"] == sum(c["count"] for c in r["byCategory"])
    assert all(0 <= c["resolved"] <= c["count"] for c in r["byCategory"])
    assert r["coveredFrom"] is not None and r["from"] <= r["coveredFrom"]
    assert "Atenție" in r["note"]["ro"]  # the recording covers only part of the window
    wider = reports.report_summary("cl_20261102_mocioni", 2000)
    assert wider["total"] >= r["total"]
    # nothing but counts leaves the module: no text, points or ids of the reports
    blob = json.dumps(r, ensure_ascii=False)
    for rep in json.loads(sorted((DATA_DIR / "live" / "sesizari").glob("*.json"))[-1].read_text())[:50]:
        assert rep["id"] not in blob
        if rep.get("descriere") and len(rep["descriere"]) > 12:
            assert rep["descriere"] not in blob
    assert "coordinates" not in blob and "descriere" not in blob
    print("Mocioni sesizări 500 m:", r["total"], r["byCategory"])


@needs_data
@needs_sesizari
def test_hero_period_outside_recording_is_null():
    r = reports.report_summary("cl_20261108_16dec")
    assert r["total"] is None and r["byCategory"] == [] and r["coveredFrom"] is None
    assert "necunoscute" in r["note"]["ro"]


@needs_data
@needs_sesizari
def test_reports_endpoint(client):
    res = client.get("/api/closures/cl_20261102_mocioni/reports?radius=500")
    assert res.status_code == 200 and res.json()["radiusMeters"] == 500
    assert "from" in res.json()
    assert client.get("/api/closures/cl_20261102_mocioni/reports?radius=0").status_code == 422
