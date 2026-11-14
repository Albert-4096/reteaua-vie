"""L3 on synthetic numbers (no recording, no City Hall data)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics import gps_health, reliability


def _ev(delays, trip="t", n_trips=1):
    rows = [{"delay_sec": d, "trip_id": f"{trip}{i % n_trips}", "service_date": "2026-11-13"} for i, d in enumerate(delays)]
    return pd.DataFrame(rows)


def test_punctuality_classes_and_small_samples_are_inconclusive():
    p = reliability._punct(_ev([-120, 0, 100, 400, 700]), np.random.default_rng(1))
    assert (p["early"], p["onTime"], p["late"], p["veryLate"]) == (0.2, 0.4, 0.2, 0.2)
    assert p["n"] == 5 and p["conclusive"] is False
    assert reliability._punct(_ev([]), np.random.default_rng(1))["n"] == 0


def test_bootstrap_interval_contains_the_share_and_uses_trips_as_blocks():
    d = [0] * 50 + [900] * 50
    p = reliability._punct(_ev(d, n_trips=20), np.random.default_rng(1))
    assert p["trips"] == 20 and p["conclusive"] is True
    assert p["ci"][0] <= p["onTime"] <= p["ci"][1]


def test_bunching_ignores_what_the_timetable_already_does():
    e = pd.DataFrame({"route_id": "A", "direction_id": 0, "stop_id": "s", "vehicle_id": ["v1", "v2", "v3", "v4"],
                      "arr": [1000.0, 1060.0, 5000.0, 5050.0], "sched_arr": [900.0, 1500.0, 4900.0, 4960.0]})
    b = reliability._bunching(e)
    assert b.tolist() == [True, True, False, False]       # the last pair is 90 s apart in the timetable too


def test_headway_awt():
    assert reliability._awt(np.array([10.0, 10.0])) == 5.0
    assert reliability._awt(np.array([])) is None


def _rep(rows):
    return pd.DataFrame(rows, columns=["vid", "t", "trip", "x", "y", "stopped"])


def test_silent_gap_mid_trip_and_frozen_position():
    r = _rep([("a", 0, "t1", 0, 0, False), ("a", 60, "t1", 0, 0, False), ("a", 2000, "t1", 0, 0, False),   # 32 min silent
              ("b", 0, "t1", 0, 0, False), ("b", 400, "t1", 5, 0, False), ("b", 800, "t1", 8, 0, False),   # still 13 min
              ("c", 0, "t1", 0, 0, True), ("c", 900, "t1", 0, 0, True)])                                  # at a stop: fine
    gaps = gps_health._episodes(r, False)
    assert gaps["vid"].tolist() == ["a"] and round(float(gaps["min"].iloc[0])) == 32
    frozen = gps_health._episodes(r, True)
    assert set(frozen["vid"]) == {"a", "b"} and "c" not in set(frozen["vid"])


def test_a_new_trip_resets_the_gap():
    r = _rep([("a", 0, "t1", 0, 0, False), ("a", 3000, "t2", 0, 0, False)])
    assert gps_health._episodes(r, False).empty


def test_a_single_vehicle_is_never_a_conclusive_punctuality():
    """Line 23 on 14 Nov: one bus, trips labelled in sequence, delay growing -157 s to +2,600 s. Hand check of its
    trips against GTFS stop_times: it left the terminal 4 to 35 min after the labelled trip's departure and
    matched the next scheduled trip better, so the label may be offset. One vehicle cannot give a line's punctuality."""
    d = [100.0, 900.0, 1500.0, 2000.0, 2600.0] * 8
    e = _ev(d, n_trips=20)
    e["vehicle_id"] = "GOB"
    p = reliability._punct(e, np.random.default_rng(1))
    assert p["conclusive"] is False and p["vehicles"] == 1 and "singur vehicul" in p["reason"]
    e["vehicle_id"] = [f"V{i % 3}" for i in range(len(e))]
    q = reliability._punct(e, np.random.default_rng(1))
    assert q["conclusive"] is True and q["reason"] is None
