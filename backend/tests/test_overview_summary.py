"""Step 0 overview (SPEC §6.10) on the real prepared cases and vehicle recording."""

from __future__ import annotations

import shutil

import pytest

from app.common import state
from app.common.timeutil import parse_iso
from app.overview import summary
from tests.conftest import DATA_DIR, needs_data

HAS_CASES = (DATA_DIR / "state" / "closures" / "cl_20261108_16dec.impact.json").is_file()
needs_cases = pytest.mark.skipif(not HAS_CASES, reason="no prepared cases (make precompute)")


@pytest.fixture
def cases_copy(isolated_state):
    """The three prepared closures in a temp state dir, so a test can publish one."""
    src = DATA_DIR / "state" / "closures"
    for p in src.glob("cl_2026110*"):
        shutil.copy(p, isolated_state.state_dir / "closures" / p.name)
    return isolated_state


def _publish(cid: str) -> None:
    c = state.read("closures", cid)
    c["status"] = "published"
    state.write("closures", cid, c)


@needs_data
@needs_cases
def test_nothing_published_means_no_active_closure(cases_copy):
    o = summary.overview(parse_iso("2026-11-08T12:00:00+02:00"))
    assert o["activeClosures"] == [] and o["upcomingClosures"] == []
    assert o["ghostDeparturesToday"] == 0  # computed: no published closure loses a departure
    assert o["at"] == "2026-11-08T12:00:00+02:00"


@needs_data
@needs_cases
def test_published_hero_counts_its_lost_departures_today(cases_copy):
    _publish("cl_20261108_16dec")
    impact = state.read("closures", "cl_20261108_16dec", state.PART_IMPACT)
    o = summary.overview(parse_iso("2026-11-08T12:00:00+02:00"))
    assert [c["id"] for c in o["activeClosures"]] == ["cl_20261108_16dec"]
    # the whole 10:00-18:00 window lies in that day: ghost departures = the impact total
    assert o["ghostDeparturesToday"] == impact["totals"]["departuresLost"] > 0
    before = summary.overview(parse_iso("2026-11-03T09:00:00+02:00"))
    assert [c["id"] for c in before["upcomingClosures"]] == ["cl_20261108_16dec"]
    assert before["ghostDeparturesToday"] == 0
    assert summary.overview(parse_iso("2026-11-20T09:00:00+02:00"))["upcomingClosures"] == []
    print("ghost departures 8 Nov:", o["ghostDeparturesToday"])


@needs_data
def test_vehicles_from_newest_recording_on_demo_clock():
    o = summary.overview(parse_iso("2026-11-08T12:00:00+02:00"))
    if any((DATA_DIR / "live" / "vehicles").glob("*.jsonl.gz")):
        assert o["vehiclesLive"] > 0 and o["vehiclesAt"] is not None
        assert any("instantaneu" in (p["note"] or "") for p in o["provenance"])
    assert o["compliance"] is None or set(o["compliance"]) == {"covered", "partial", "missing"}


@needs_data
def test_overview_endpoint(client):
    res = client.get("/api/overview", params={"at": "2026-11-08T12:00:00+02:00"})
    assert res.status_code == 200 and res.json()["at"] == "2026-11-08T12:00:00+02:00"
    assert client.get("/api/overview?at=2026-11-08T12:00:00+02:00").status_code == 200
    assert client.get("/api/overview?at=nonsense").status_code == 422
