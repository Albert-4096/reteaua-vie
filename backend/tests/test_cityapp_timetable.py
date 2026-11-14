"""R27: the City Hall timetable check, with the HTTP call replaced (the suite never calls the city)."""

from __future__ import annotations

from datetime import date

import pytest

from app.cityapp import timetable_check as tc
from tests.conftest import needs_data

MOCIONI = "cl_20261102_mocioni"
DAY = date(2026, 11, 14)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    calls: list[str] = []

    def get(stop_id, day):
        calls.append(stop_id)
        return {"date": day.isoformat(), "lines": [
            {"routeId": "R_AB_M32", "directionId": 0, "headsign": "x", "times": ["06:10", "23:50", "00:05"]},
            {"routeId": "R_AB_33", "directionId": 0, "headsign": "y", "times": ["07:00"]}]}

    monkeypatch.setattr(tc, "_get", get)
    monkeypatch.setattr(tc, "_cache_path", lambda s, d: tmp_path / d.isoformat() / f"{s}.json")
    return calls


def test_times_after_midnight_roll_to_next_day():
    from app.common.timeutil import local_midnight
    from datetime import timedelta
    start = local_midnight(DAY)
    assert tc._times_in_window(["23:50", "00:05"], DAY, start, start + timedelta(days=1)) == 1
    assert tc._times_in_window(["23:50", "00:05"], DAY, start, start + timedelta(days=2)) == 2


@needs_data
def test_lists_departures_of_lost_lines_once_per_stop(fake):
    r = tc.check(MOCIONI, DAY)
    assert r["state"] == "ok" and r["stopsChecked"] == r["stopsTotal"] == len(fake)
    assert r["departuresListed"] > 0 and all(i["shortName"].startswith("M32") for i in r["items"])
    assert "de marcat" in r["sentence"].ro and "orar din API-ul Primăriei" in r["label"]
    n = len(fake)
    tc.check(MOCIONI, DAY)            # second run: all from the cache, no new call
    assert len(fake) == n


@needs_data
def test_budget_and_failure_never_invent_numbers(fake, monkeypatch):
    monkeypatch.setattr(tc, "MAX_CALLS", 2)
    r = tc.check(MOCIONI, DAY)
    assert r["stopsChecked"] == 2 and r["capped"] and len(fake) == 2
    monkeypatch.setattr(tc, "MAX_CALLS", 30)
    monkeypatch.setattr(tc, "_get", lambda s, d: (_ for _ in ()).throw(tc.httpx.ConnectError("down")))
    monkeypatch.setattr(tc, "_cache_path", lambda s, d: tc.get_settings().cache_dir / "nonexistent-test" / f"{s}.json")
    r = tc.check(MOCIONI, DAY)
    assert r["state"] == "unavailable" and r["departuresListed"] == 0 and "necunoscut" in r["sentence"].ro


@needs_data
def test_not_in_force_makes_no_call(fake, client):
    r = tc.check(MOCIONI, date(2027, 3, 1))
    assert r["state"] == "not_in_force" and not fake
    assert client.get(f"/api/closures/{MOCIONI}/timetable-check", params={"date": "nope"}).status_code == 422
