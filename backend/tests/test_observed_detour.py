"""L1-B detour cost: stretch detection, planned and measured times, statistics (synthetic data built here)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.observed import detour_cost as dc
from app.observed import timetable as tt


def _plan(tid: str, stops: list[str], times: list[int], route: str = "R_AB_M1") -> tt.TripPlan:
    t = np.array(times)
    return tt.TripPlan(trip_id=tid, route_id=route, direction_id=1, service_id="S", shape_id="",
                       seq=np.arange(1, len(stops) + 1), stop_ids=tuple(stops), arr_sec=t, dep_sec=t,
                       feed_version="x", feed_sha="x")


def _tt(plans: list[tt.TripPlan]) -> tt.Timetable:
    return tt.Timetable(sha="x", version="x", trips={p.trip_id: p for p in plans}, stop_xy={}, shapes={},
                        stop_names={})


def test_changed_blocks_kinds():
    assert dc.changed_blocks(tuple("12345"), tuple("12945")) == [("detour", (1, 4), (1, 4))]
    # the terminal moved (M32): the anchor after it is kept
    assert dc.changed_blocks(tuple("MCIX"), tuple("NPX")) == [("start_moved", (0, 4), (0, 3))]
    # the line now starts at the anchor (M36 tur)
    assert dc.changed_blocks(tuple("MCIX"), tuple("IX")) == [("truncated_start", (0, 3), (0, 1))]
    assert dc.changed_blocks(tuple("XICM"), tuple("XIR")) == [("end_moved", (1, 4), (1, 3))]
    assert dc.changed_blocks(tuple("XICM"), tuple("XI")) == [("truncated_end", (1, 4), (1, 2))]


def test_weighted_median_matches_repeat():
    rng = np.random.default_rng(1)
    for _ in range(50):
        v = np.sort(rng.normal(size=rng.integers(1, 12)))
        w = rng.integers(0, 4, size=len(v))
        got = dc._wmedian_sorted(v, w)
        if w.sum() < dc.MIN_OBS:
            assert np.isnan(got)
        else:
            assert np.isclose(got, np.median(np.repeat(v, w)))


def test_boot_median_threshold_and_interval():
    rng = np.random.default_rng(2)
    few = dc.boot_median(np.full(dc.MIN_TRIPS - 1, 60.0), rng)
    assert few.n == dc.MIN_TRIPS - 1 and not few.conclusive and few.sec == few.low == few.high == 60.0
    many = dc.boot_median(np.arange(40, dtype=float), rng)
    assert many.conclusive and many.low <= many.sec <= many.high
    assert dc.boot_median(np.array([]), rng).sec is None


def test_stretches_planned_and_measured():
    before = _tt([_plan("T1", ["X", "I", "C", "M"], [0, 60, 120, 240]),
                  _plan("T2", ["X", "I", "C", "M"], [600, 660, 720, 840]),
                  _plan("O1", ["A", "B"], [0, 60], route="R_AB_OTHER")])
    after = _tt([_plan("T1", ["X", "I", "R"], [0, 60, 120]),
                 _plan("T2", ["X", "I", "R"], [600, 660, 720]),
                 _plan("O1", ["A", "Z"], [0, 60], route="R_AB_OTHER")])
    closure = {"routeIds": ["R_AB_M1"], "routeActions": [{"routeId": "R_AB_M1", "suspendedStopIds": ["C", "M"]}]}
    rows = dc.stretches(closure, before, after, [])
    assert len(rows) == 1
    s = rows[0]
    assert (s.kind, s.before, s.after) == ("end_moved", ("I", "C", "M"), ("I", "R"))
    assert [(b, a) for _t, _d, b, a in s.planned] == [(180.0, 60.0), (180.0, 60.0)]   # 1 min instead of 3
    # a change that does not touch the closure's stops is left out
    assert dc.stretches({**closure, "routeActions": [{"routeId": "R_AB_M1", "suspendedStopIds": ["Q"]}]},
                        before, after, []) == []
    ev = pd.DataFrame([
        # trip, date, stop, index, dep, arr, planned dep/arr
        ("T1", "2026-11-14", "I", 1, 1000.0, 990.0, 1000.0, 1000.0),
        ("T1", "2026-11-14", "R", 2, np.nan, 1075.0, 1060.0, 1060.0),
        ("T2", "2026-11-14", "I", 1, 2000.0, 1990.0, 2000.0, 2000.0),   # no arrival at R: not measured
    ], columns=["trip_id", "service_date", "stop_id", "stop_index", "dep", "arr", "sched_dep", "sched_arr"])
    ev["route_id"], ev["direction_id"] = "R_AB_M1", 1
    runs = dc.measured_runs(ev, s)
    assert list(runs["trip_id"]) == ["T1"] and runs["run"].iloc[0] == 75.0 and runs["planned"].iloc[0] == 60.0
