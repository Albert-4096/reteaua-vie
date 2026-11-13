"""precompute: every app/<pkg>/warm*.py is found and called; a failing warm is not fatal."""

from __future__ import annotations

import sys
import types

from app import precompute


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
