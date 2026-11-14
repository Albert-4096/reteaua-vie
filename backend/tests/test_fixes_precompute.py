"""precompute: every app/<pkg>/warm*.py is found and called; a failing warm is not fatal."""

from __future__ import annotations

import sys
import types

from app import precompute
from tests.conftest import needs_data


def test_warm_modules_are_found():
    names = precompute.warm_modules()
    assert all(n.startswith("app.") and n.split(".")[-1].startswith("warm") for n in names)
    assert names == sorted(names)


def test_run_warms_calls_each_and_survives_a_failure(monkeypatch, capsys):
    seen = []
    ok = types.ModuleType("fake_warm_ok")
    ok.warm = lambda ids: seen.append(("ok", ids))
    bad = types.ModuleType("fake_warm_bad")

    def boom(ids):
        raise RuntimeError("no r5py here")

    bad.warm = boom
    none = types.ModuleType("fake_warm_none")
    for m in (ok, bad, none):
        monkeypatch.setitem(sys.modules, m.__name__, m)
    monkeypatch.setattr(precompute, "warm_modules", lambda: ["fake_warm_bad", "fake_warm_none", "fake_warm_ok"])
    out = precompute.run_warms(["cl_a", "cl_b"])
    assert out == {"fake_warm_bad": "fail", "fake_warm_none": "skip", "fake_warm_ok": "ok"}
    assert seen == [("ok", ["cl_a", "cl_b"])]
    assert "FAIL fake_warm_bad: RuntimeError: no r5py here" in capsys.readouterr().out


def test_run_warms_skips_a_module_whose_inputs_did_not_change(isolated_state, monkeypatch, capsys):
    """R2: a warm run skips what nothing changed for; the live warm-up always runs."""
    calls = []
    mods = {}
    for name in ("fake_warm_a", "app.live.warm"):
        m = types.ModuleType(name)
        m.warm = lambda ids, name=name: calls.append(name)
        mods[name] = m
        monkeypatch.setitem(sys.modules, name, m)
    monkeypatch.setattr(precompute, "get_settings", lambda: isolated_state)
    monkeypatch.setattr(precompute, "warm_modules", lambda: ["fake_warm_a", "app.live.warm"])
    assert precompute.run_warms(["cl_a"], "s1") == {"fake_warm_a": "ok", "app.live.warm": "ok"}
    assert precompute.run_warms(["cl_a"], "s1") == {"fake_warm_a": "unchanged", "app.live.warm": "ok"}
    assert precompute.run_warms(["cl_a"], "s2") == {"fake_warm_a": "ok", "app.live.warm": "ok"}
    assert precompute.run_warms(["cl_a"]) == {"fake_warm_a": "ok", "app.live.warm": "ok"}   # no stamp: no skip
    assert calls.count("fake_warm_a") == 3 and calls.count("app.live.warm") == 4
    assert "skip fake_warm_a: nothing changed" in capsys.readouterr().out


@needs_data
def test_warm_stamp_changes_with_a_stored_closure(isolated_state, monkeypatch):
    from app.common import state

    before = precompute.warm_stamp()
    assert precompute.warm_stamp() == before
    state.write("closures", "cl_20261114_0000_abcdef", {
        "id": "cl_20261114_0000_abcdef", "status": "draft", "createdAt": "2026-11-14T00:00:00+02:00",
        "title": {"ro": "t"}, "kind": "drawn", "geometry": None, "bufferMeters": 30, "direction": "both",
        "window": {"start": "2026-11-15T10:00:00+02:00", "end": "2026-11-15T12:00:00+02:00"}, "routeIds": []})
    assert precompute.warm_stamp() != before
