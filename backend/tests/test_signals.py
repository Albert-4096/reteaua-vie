"""R9: per-signal waits and the signals on a detour (read-only, real recording)."""

from __future__ import annotations

import pytest

from app.signals import waits
from tests.conftest import needs_data


@needs_data
def test_ranking_is_sorted_and_labelled():
    try:
        r = waits.ranking(10)
    except RuntimeError:
        pytest.skip("L0 not built here")
    assert r.signals and [s.minutes for s in r.signals] == sorted((s.minutes for s in r.signals), reverse=True)
    assert all(s.signalId.startswith("sig_") and s.vehicles >= 1 for s in r.signals)
    assert "nu e simulare" in r.label.ro and "nu o economie promisă" in r.label.ro and r.provenance


@needs_data
def test_detour_signals_are_proposals_with_departures():
    try:
        r = waits.on_detour("cl_20261108_16dec")
    except RuntimeError:
        pytest.skip("L0 not built here")
    assert r.status == "ok" and r.signals
    assert "Nu propunem durate" in r.proposal.ro or "nu propunem durate" in r.proposal.ro.lower()
    assert any(s.standingMinutes for s in r.signals) and all(s.departuresInWindow >= 0 for s in r.signals)
    assert any("necunoscut" in s.standingNote for s in r.signals) or all(s.standingMinutes for s in r.signals)


@needs_data
def test_endpoints(client):
    r = client.get("/api/signals/waits", params={"limit": 3})
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        assert len(r.json()["signals"]) <= 3
        layer = client.get("/api/layers/standstill", params={"limit": 5}).json()
        assert layer["layer"] == "standstill" and layer["features"]
