"""A8 on tiny synthetic patterns and departure times."""

from __future__ import annotations

import numpy as np

from app.analytics import corridors
from app.common.gtfs import Pattern


def _p(route, stops, d=0):
    return Pattern(route_id=route, direction_id=d, stop_ids=tuple(stops), headsign="", trips=1, share=1.0)


def test_shared_stretch_needs_same_lines_and_enough_stops(monkeypatch):
    pats = {("A", 0): _p("A", "1 2 3 4 5".split()), ("B", 0): _p("B", "9 2 3 4 8".split()),
            ("C", 0): _p("C", "7 4 5 6".split())}
    monkeypatch.setattr(corridors.gtfs, "stop_patterns", lambda: pats)
    found = {k[1]: k[0] for k in corridors._stretches(3)}
    assert found == {("2", "3", "4"): ("A", "B")}      # 4-5 is shared by A and C but only 2 stops long
    assert ("4", "5") in {k[1] for k in corridors._stretches(2)}


def test_two_lines_together_are_a_pluton_and_a_shift_evens_them_out():
    a = np.arange(0, 3600, 720.0)                     # every 12 min
    together = {"A": a, "B": a.copy()}
    st = corridors._gap_stats(np.concatenate(list(together.values())))
    assert corridors._pattern(st["cv"]) == "în pluton" and st["min"] == 0.0 and st["close"] > 0
    shifts, cv_after, max_gap = corridors.propose(together)
    assert list(shifts) == ["B"] and 5 <= abs(shifts["B"]) <= 7
    assert cv_after < 0.3 and max_gap <= 8


def test_even_lines_get_no_proposal_and_few_departures_no_pattern():
    a = np.arange(0, 3600, 720.0)
    assert corridors.propose({"A": a, "B": a + 360}) is None
    assert corridors._gap_stats(np.array([0.0, 600.0]))["cv"] is None
    assert corridors._pattern(None) is None
