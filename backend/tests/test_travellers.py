"""R20: the board count is the official sesizări since a moment, not a second inbox.

The link to Sesizări is frontend. Backend: `since` on GET /api/closures/{id}/reports.
Counts and categories only. POST /api/problem-report (our own signal, fixed categories) refuses free text.
"""

from __future__ import annotations

import json

import pytest

from app.common.timeutil import iso, parse_iso
from app.live import reports
from tests.conftest import DATA_DIR, needs_data

HAS_SESIZARI = any((DATA_DIR / "live" / "sesizari").glob("*.json"))
HAS_CASES = (DATA_DIR / "state" / "closures" / "cl_20261102_mocioni.json").is_file()
needs_sesizari = pytest.mark.skipif(not (HAS_SESIZARI and HAS_CASES), reason="no sesizări recording or cases")
MOCIONI = "cl_20261102_mocioni"


@needs_data
@needs_sesizari
def test_since_narrows_the_count_and_keeps_only_counts():
    base = reports.report_summary(MOCIONI, 500)
    assert base["total"] is not None and base["total"] > 0
    lo, hi = parse_iso(base["coveredFrom"]), parse_iso(base["coveredTo"])
    mid = lo + (hi - lo) / 2
    narrow = reports.report_summary(MOCIONI, 500, since=mid)
    assert narrow["total"] is not None and narrow["total"] <= base["total"]
    assert narrow["from"] == iso(mid)
    assert narrow["total"] == sum(c["count"] for c in narrow["byCategory"])
    blob = json.dumps(narrow, ensure_ascii=False)
    assert "descriere" not in blob and "coordinates" not in blob
    # a since at the end of the recording asks for a span we did not cover: unknown, not 0
    outside = reports.report_summary(MOCIONI, 500, since=hi)
    assert outside["total"] is None and outside["byCategory"] == []


@needs_data
@needs_sesizari
def test_since_on_the_endpoint_and_no_free_text(client):
    base = reports.report_summary(MOCIONI, 500)
    mid = parse_iso(base["coveredFrom"]) + (parse_iso(base["coveredTo"]) - parse_iso(base["coveredFrom"])) / 2
    res = client.get(f"/api/closures/{MOCIONI}/reports", params={"radius": 500, "since": iso(mid)})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] is not None and body["from"] == iso(mid)
    assert "descriere" not in json.dumps(body)
    assert client.get(f"/api/closures/{MOCIONI}/reports", params={"since": "not-a-time"}).status_code == 422
    assert client.post("/api/problem-report", json={
        "stopId": "356", "category": "bus_did_not_come", "deviceKey": "phone-aaaaaaaa1", "text": "the bus"}).status_code == 422   # no free text, ever
