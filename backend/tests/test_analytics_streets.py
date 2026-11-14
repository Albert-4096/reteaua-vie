"""R8/L4 helpers on synthetic data."""

from __future__ import annotations

from app.analytics import streets


def test_cache_returns_the_same_object_until_the_stamp_changes(monkeypatch):
    streets._memo.clear()
    calls = []
    monkeypatch.setattr(streets.store, "_stamp", lambda: (1, 1))
    f = lambda: calls.append(1) or {"x": len(calls)}
    assert streets._cached("k", f) is streets._cached("k", f) and len(calls) == 1
    monkeypatch.setattr(streets.store, "_stamp", lambda: (2, 1))
    assert streets._cached("k", f) == {"x": 2}


def test_thresholds_are_stated():
    assert streets.STOP_DIST_M == 30 and streets.MIN_RUNS >= 10
    assert "30 m" in streets.METHOD_L4.ro or "30" in streets.METHOD_L4.ro
