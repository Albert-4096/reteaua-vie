"""Live check (SPEC §6.8) on the real recording: Mocioni shows real skipped/served/unknown counts."""

from __future__ import annotations

import pytest

from app.live import check
from tests.conftest import DATA_DIR, needs_data

HAS_RECORDING = any((DATA_DIR / "live" / "vehicles").glob("*.jsonl.gz"))
HAS_CASES = (DATA_DIR / "state" / "closures" / "cl_20261102_mocioni.analysis.json").is_file()
needs_recording = pytest.mark.skipif(not (HAS_RECORDING and HAS_CASES), reason="no vehicle recording or cases")


def test_place_between_first_last_and_on_trip():
    old = ["356", "357", "291", "292", "293"]
    new = ("478", "479", "292", "293")
    # the old route started at 356: passed once the trip leaves 292 (its first anchor)
    assert check.place_on_trip("356", old, new) == check.Place("first", 1, 2)
    old1 = ["268", "269", "352", "353", "356"]
    new1 = ("268", "269", "352", "478")
    # the old route ended at 353: passed when the trip runs on from 352 toward its new end
    assert check.place_on_trip("353", old1, new1) == check.Place("last", 2, 2.5)
    assert check.place_on_trip("x", ["a", "x", "c"], ("a", "b", "c")) == check.Place("between", 0, 2)
    assert check.place_on_trip("b", [], ("a", "b", "c")) == check.Place("on_trip", 0.5, 1.5)
    assert check.place_on_trip("zz", ["a"], ("a",)) is None


def test_period_label_is_romanian_first():
    from app.common.timeutil import parse_iso

    lab = check.period_label(parse_iso("2026-11-13T13:47:00+02:00"), parse_iso("2026-11-14T20:00:00+02:00"))
    assert lab == {"ro": "Înregistrare reală, 13–14 nov", "en": "Real recording, 13–14 Nov"}


@needs_data
@needs_recording
def test_mocioni_live_check_counts_real_passages():
    r = check.compute_live_check("cl_20261102_mocioni")
    s = r["summary"]
    assert r["source"] == "replay"
    assert r["label"]["ro"].startswith("Înregistrare reală, ")
    # real counts from the recording, never null when the recording covers the window
    assert s["stopsSkipped"] is not None and s["stopsSkipped"] > 0
    assert s["stopsServedAnyway"] is not None and s["stopsUnknown"] is not None
    assert s["vehiclesSeen"] >= 1
    states = [o["state"] for o in r["observations"]]
    assert states.count("skipped") == s["stopsSkipped"]
    assert states.count("served") == s["stopsServedAnyway"]
    assert states.count("unknown") == s["stopsUnknown"]
    assert all(o["served"] == (o["state"] == "served") for o in r["observations"])
    # byStop rows add up to the summary and cover the suspended stops of the 4.29 normal pattern
    assert sum(b["skipped"] for b in r["byStop"]) == s["stopsSkipped"]
    assert {b["stopId"] for b in r["byStop"]} >= {"353", "356", "357"}
    assert r["from"] >= r["recordedFrom"] and r["to"] <= r["recordedTo"]
    assert "4.29" in r["note"]["en"] and r["provenance"]
    print("Mocioni live:", s, r["from"], r["to"])


@needs_data
@needs_recording
@pytest.mark.parametrize("cid", ["cl_20261108_16dec", "cl_20261107_e3"])
def test_past_windows_answer_null_not_zero(cid):
    r = check.compute_live_check(cid)
    assert r["source"] is None and r["observations"] == []
    assert set(r["summary"].values()) == {None}
    assert "necunoscute" in r["note"]["ro"]


@needs_data
@needs_recording
def test_live_endpoint(client):
    res = client.get("/api/closures/cl_20261102_mocioni/live")
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "replay" and "from" in body and body["summary"]["stopsSkipped"] > 0
    assert client.get("/api/closures/cl_20261108_16dec/live").json()["source"] is None
    assert client.get("/api/closures/no_such_closure/live").status_code == 404
