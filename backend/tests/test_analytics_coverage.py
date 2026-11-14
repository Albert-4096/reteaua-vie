"""A10 on synthetic numbers: classes, weak coverage and the weighted median."""

from __future__ import annotations

import numpy as np

from app.analytics import coverage


def test_classify_edges():
    f = np.array([0.0, 1.9, 2.0, 3.9, 4.0, 7.9, 8.0, 5.0])
    near = np.array([False, True, True, True, True, True, True, False])
    assert coverage._classify(f, near).tolist() == [0, 1, 2, 2, 3, 3, 4, 0]


def test_zone_row_counts_weak_residents_and_median():
    res = np.array([100.0, 50.0, 50.0, 300.0])
    freq = np.array([0.0, 1.0, 3.0, 9.0])
    cls = coverage._classify(freq, np.array([False, True, True, True]))
    r = coverage._zone_row("z", "Zona", res, cls, freq)
    assert r["byClass"] == [100, 50, 50, 0, 300]
    assert r["weakResidents"] == 150 and r["weakShare"] == 0.3
    assert r["medianPerHour"] == 9.0 and r["residents"] == 500


def test_empty_zone_has_no_share():
    r = coverage._zone_row("z", "Zona", np.zeros(0), np.zeros(0, dtype=np.int8), np.zeros(0))
    assert r["weakShare"] is None and r["medianPerHour"] is None
