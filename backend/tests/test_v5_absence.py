"""V5: missing GPS never proves a trip did not run. In the O2, R5 and L3 output and strings, „nu a circulat”,
„neefectuată” and their English twins appear only negated („nu e «neefectuată»”) or, for O2, after a person's R4
confirmation (never here: these tests make none)."""

from __future__ import annotations

import json
import re

import pytest

from tests.conftest import needs_data

FORBIDDEN = re.compile(r"(nu|n-a|n-au) (a |au )?circulat|nu circul[aă]|neefectuat|did not run|never ran|was not run|were not run|not operated",
                       re.IGNORECASE)
NEGATION = re.compile(r"(nu|not|never|nici|no)\W{0,3}[^.]{0,25}$", re.IGNORECASE)


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from strings(v)
    elif hasattr(obj, "model_dump"):
        yield from strings(obj.model_dump(mode="json"))


def offenders(obj) -> list[str]:
    bad = []
    for s in strings(obj):
        for m in FORBIDDEN.finditer(s):
            if not NEGATION.search(s[max(0, m.start() - 30):m.start()]) and "neefectuat" not in s[max(0, m.start() - 8):m.start() + 1] + "x":
                bad.append(s[max(0, m.start() - 40):m.end() + 20])
    return bad


def test_the_checker_catches_a_claim_and_allows_a_negation():
    assert offenders({"a": "Linia 23 nu a circulat sâmbătă"})
    assert offenders({"a": "cursa neefectuată"})
    assert not offenders({"a": "nu e „cursă neefectuată” (încadrarea o face SMTT)"})
    assert not offenders({"a": "we never say a trip did not run"})


@needs_data
def test_o2_output_never_claims_a_trip_did_not_run(client):
    from app.live import missing
    res = missing.with_decisions(missing.prepared("case_l23"))
    assert res["routes"], "case_l23 has flagged lines"
    assert offenders(res) == []
    assert offenders(client.get("/api/live/missing.csv", params={"case": "case_l23"}).text) == []
    assert offenders(client.get("/api/live/missing", params={"case": "case_l23"}).json()) == []


@needs_data
def test_r5_km_never_reads_the_live_data_and_never_claims_absence():
    from app.cityapp import km
    src = open(km.__file__, encoding="utf-8").read()
    assert "app.live" not in src and "vehicles" not in src.replace("trolleybus", "")   # timetable + notice only
    for cid in ("cl_20261108_16dec", "cl_20261107_e3"):
        assert offenders(km.km_report(cid)) == []


@needs_data
def test_l3_reliability_and_gps_health_never_claim_absence(client):
    for path in ("/api/reliability/lines", "/api/reliability/vehicles"):
        r = client.get(path)
        if r.status_code != 200:
            pytest.skip(f"{path} not available here ({r.status_code})")
        assert offenders(r.json()) == [], path
