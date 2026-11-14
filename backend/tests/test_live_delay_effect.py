"""R25 on the real data: the Mocioni diversion (published, in GTFS 4.30) against our L0 timetable,
and V5 for R18/R25: no output says a trip did not run."""

from __future__ import annotations

import json

import pytest

from tests.conftest import DATA_DIR, needs_data

needs_l0 = pytest.mark.skipif(not (DATA_DIR / "cache" / "observed").is_dir(), reason="no observed timetable (L0)")
needs_moc = pytest.mark.skipif(not (DATA_DIR / "state" / "closures" / "cl_20261102_mocioni.json").is_file(),
                               reason="no stored Mocioni closure")
FORBIDDEN = ("nu a circulat", "n-a circulat", "neefectuat", "anulat", "did not run", "not run", "cancel")


@needs_data
@needs_l0
@needs_moc
def test_mocioni_row_has_n_interval_and_verdict(client):
    r = client.get("/api/closures/cl_20261102_mocioni/delay-effect")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok" and body["minTrips"] == 10
    total = body["total"]
    assert total["n"] >= 10 and total["verdict"] in ("masurat", "neconcludent")
    assert total["low"] is not None and total["low"] <= total["addedSec"] <= total["high"]
    assert {s["shortName"] for s in body["stretches"]} >= {"M32"}
    for s in body["stretches"]:
        e = s["effect"]
        assert e["verdict"] == "neconcludent" or (e["n"] >= 10 and not (e["low"] <= 0 <= e["high"]))


def test_unknown_closure_is_404(client):
    assert client.get("/api/closures/nu_exista/delay-effect").status_code == 404


@needs_data
@needs_l0
@needs_moc
def test_v5_no_output_says_a_trip_did_not_run(client):
    """V5: missing GPS never becomes „did not run”; R18 and R25 never say it (only an R4 confirmation could)."""
    texts = [client.get("/api/closures/cl_20261102_mocioni/delay-effect").text,
             client.get("/api/live/deviations", params={"from": "2026-11-14T06:00:00+02:00",
                                                        "to": "2026-11-14T13:00:00+02:00"}).text]
    for t in texts:
        low = json.loads(t)
        flat = json.dumps(low, ensure_ascii=False).lower()
        assert not [w for w in FORBIDDEN if w in flat], [w for w in FORBIDDEN if w in flat]
