"""R14: the daily registry (hash chain) on the real recording; files go to a temp dir."""

from __future__ import annotations

from datetime import date

import pytest

from app.evidence.journal import canon, sha
from app.registry import daily
from tests.conftest import needs_data

DAY = date(2026, 11, 13)


@pytest.fixture(autouse=True)
def tmp_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(daily, "_dir", lambda: tmp_path)


@needs_data
def test_past_day_is_written_once_and_verifies():
    if DAY not in daily.recorded_days():
        pytest.skip("no recording of 13 Nov here")
    e = daily.entry(DAY)
    assert e["final"] and e["recording"]["l0Complete"] and e["prevHash"] == daily.GENESIS
    assert e["chainHash"] == sha(e["prevHash"] + e["rawSha256"] + e["rollupSha256"])
    rollup = {k: e[k] for k in ("date", "recording", "lines", "feedVersion", "rollupVersion")}
    assert sha(canon(rollup)) == e["rollupSha256"]
    again = daily.entry(DAY, verify=True)
    assert again["verified"] is True and again["chainHash"] == e["chainHash"]
    assert (daily._dir() / "20261113.json").is_file()


@needs_data
def test_trips_seen_never_exceed_what_the_timetable_has_in_the_recording():
    if DAY not in daily.recorded_days():
        pytest.skip("no recording of 13 Nov here")
    for ln in daily.entry(DAY)["lines"]:
        assert ln["tripsSeen"] >= 0 and (ln["share"] is None or ln["share"] <= 1)
        assert ln["kmNote"].startswith("estimare")


@needs_data
def test_endpoint(client):
    r = client.get("/api/registry", params={"from": "2026-11-13", "to": "2026-11-13"})
    assert r.status_code == 200 and r.json()["entries"] and r.json()["provenance"]
    assert client.get("/api/registry", params={"from": "x"}).status_code == 422


def test_trips_seen_never_exceed_scheduled_and_reliability_agrees_with_the_registry():
    """L8a + L8b on the real recording: seen <= scheduled in the recording for every line and day (trips that
    started before the recording are `tripsSeenOutside`, not seen), and /api/reliability/lines carries the same
    per-line totals as the sum of the registry's days."""
    from datetime import date

    from app.analytics import reliability
    from app.registry import daily

    days = daily.recorded_days()
    if not days:
        pytest.skip("no recording")
    reg = daily.registry(days[0], days[-1])
    tot: dict[str, list[int]] = {}
    for e in reg["entries"]:
        for ln in e["lines"]:
            assert ln["tripsSeen"] <= ln["tripsScheduledInRecording"], (e["date"], ln["shortName"], ln)
            t = tot.setdefault(ln["routeId"], [0, 0])
            t[0] += ln["tripsSeen"]
            t[1] += ln["tripsScheduledInRecording"]
    try:
        rel = reliability.report()
    except RuntimeError:
        pytest.skip("L0 not built")
    checked = 0
    for ln in rel["lines"]:
        if ln["routeId"] in tot and tot[ln["routeId"]][1]:
            assert (ln["trips"]["observed"], ln["trips"]["scheduled"]) == tuple(tot[ln["routeId"]]), ln["shortName"]
            checked += 1
    assert checked > 10
