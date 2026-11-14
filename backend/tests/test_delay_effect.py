"""R25: the extra delay a diversion adds. Pure summaries, no recording load."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.live.delay_effect import MIN_TRIPS, _effect, summarize
from app.models.delay_effect import DelayEffect


def test_under_the_threshold_is_neconcludent_and_still_has_n_and_an_interval():
    out = summarize([30.0, 40.0, 50.0, 60.0], rng=np.random.default_rng(1))
    DelayEffect.model_validate(out)
    assert out["n"] == 4 < MIN_TRIPS
    assert out["verdict"] == "neconcludent"
    assert out["low"] is not None and out["high"] is not None and out["low"] <= out["addedSec"] <= out["high"]
    assert "neconcludent" in out["text"]["ro"].lower()
    assert "weekend" in out["text"]["ro"] and "fără extrapolare" in out["text"]["ro"]


def test_zero_trips_have_no_interval():
    out = summarize([])
    assert out["verdict"] == "neconcludent" and out["n"] == 0
    assert out["addedSec"] is None and out["low"] is None and out["high"] is None


def test_a_clear_positive_delay_is_measured():
    out = summarize([120.0] * 20, rng=np.random.default_rng(2))
    assert out["verdict"] == "masurat" and out["n"] == 20
    assert out["addedSec"] == 120.0 and out["low"] > 0 and out["high"] > 0
    assert "adaugă" in out["text"]["ro"] and "weekend" in out["text"]["ro"]


def test_an_interval_through_zero_is_neconcludent():
    out = summarize([-90.0, 90.0] * 12, rng=np.random.default_rng(3))
    assert out["n"] >= MIN_TRIPS and out["verdict"] == "neconcludent"
    assert out["low"] <= 0 <= out["high"]


def test_effect_subtracts_the_trips_own_drift_and_needs_control_segments():
    # 100 s added on the stretch; the rest of the trip gained 30 s over 300 scheduled seconds,
    # and the stretch itself is 200 scheduled seconds → drift = 30/300*200 = 20 → effect 80.
    assert _effect(100.0, 200.0, 0.0, 0.0, 0, pd.Series({"gain": 30.0, "sched": 300.0, "k": 5})) == 80.0
    assert _effect(100.0, 200.0, 0.0, 0.0, 0, pd.Series({"gain": 30.0, "sched": 300.0, "k": 2})) is None
