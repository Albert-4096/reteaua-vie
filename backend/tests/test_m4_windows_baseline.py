"""T5: /windows agrees with /impact for the same decisions; a conflict common to every window is said once.

Runs on the real prepared cases in a temp DATA_DIR (state empty, everything else linked in), before
and after the D-012 clerk decisions (the 11067 gold label applied as decisions, as in eval/run.py).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import config
from app.common.timeutil import parse_iso
from app.config import TZ
from tests.conftest import needs_data

HERO = "cl_20261108_16dec"
GOLD_11067 = Path(__file__).resolve().parents[2] / "eval" / "labels" / "11067.json"


def test_split_common_keeps_only_windows_that_cover_the_range():
    from app.m4_access import windows as win

    rng = win.SearchRange(datetime(2026, 11, 8, 12, tzinfo=TZ), datetime(2026, 11, 22, 12, tzinfo=TZ), 8.0, [])
    always = ("cl_always", datetime(2026, 11, 2, tzinfo=TZ), datetime(2026, 12, 31, tzinfo=TZ))
    some = ("cl_some", datetime(2026, 11, 10, tzinfo=TZ), datetime(2026, 11, 11, tzinfo=TZ))
    common, varying = win.split_common([always, some], rng)
    assert common == [always] and varying == [some]


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("windows")
    real = config.get_settings()
    for p in real.data_dir.iterdir():
        if p.name not in ("state", "cache"):
            (tmp / p.name).symlink_to(p)
    (tmp / "cache").mkdir()
    for p in (real.data_dir / "cache").iterdir():   # reuse indexes and graphs, never the job results
        if p.name != "jobs":
            (tmp / "cache" / p.name).symlink_to(p)
    fake = config.Settings(env_file=None, data_dir=tmp, live_dir=real.live_dir, demo_now=real.demo_now,
                           data_freeze=False, public_base_url=real.public_base_url)
    import app.cases.build  # noqa: F401  (imported before patching, so the patch is undone after)
    import app.main  # noqa: F401
    from app import precompute

    mp = pytest.MonkeyPatch()
    original = config.get_settings
    for name, mod in list(sys.modules.items()):
        if name.startswith("app") and getattr(mod, "get_settings", None) is original:
            mp.setattr(mod, "get_settings", lambda: fake)
    config.ensure_dirs(fake)
    precompute.prepare_cases()
    yield fake
    mp.undo()


def _check_agrees(label: str):
    from app.m1_disruption.impact import compute_impact
    from app.m4_access import windows as win

    ws = win.suggest(HERO)
    impact = compute_impact(HERO)
    assert ws.baselineDeparturesLost == impact.totals.departuresLost, label
    assert f"față de {win.num_ro(impact.totals.departuresLost)} în fereastra din anunț" in ws.method.ro, label
    # a closure that overlaps every candidate (Mocioni, open to 31 Dec, while it conflicts with the
    # hero) is said once at the top and never counted on a row
    lo, hi = parse_iso(ws.searchFrom), parse_iso(ws.searchTo) + timedelta(hours=ws.hours)
    for c in ws.commonConflicts or []:
        assert parse_iso(c.window.start) <= lo and parse_iso(c.window.end) >= hi, label
    assert ws.method.ro.count("Toate ferestrele se suprapun") == (1 if ws.commonConflicts else 0), label
    return ws, impact


@needs_data
def test_windows_baseline_equals_impact_before_and_after_the_d012_decisions(prepared):
    from app.common import state
    from app.m1_disruption.analysis import apply_decisions

    _, before = _check_agrees("undecided")
    label = json.loads(GOLD_11067.read_text(encoding="utf-8"))
    pos, unc = set(), set()
    for a in label["gold"]["routeActions"]:
        pos |= {(str(s), a["routeId"], a["directionId"]) for s in a["suspendedStopIds"]}
        unc |= {(str(s), a["routeId"], a["directionId"]) for s in a["uncertainStopIds"]}
    rows = state.read("closures", HERO, state.PART_ANALYSIS)["stops"]
    decisions = [{"stopId": r["stopId"], "routeId": r["routeId"], "directionId": r["directionId"],
                  "confirmed": (str(r["stopId"]), r["routeId"], r["directionId"]) in pos}
                 for r in rows if r["state"] == "unsure"
                 and (str(r["stopId"]), r["routeId"], r["directionId"]) in pos | unc]
    assert decisions
    apply_decisions(HERO, decisions)
    _, after = _check_agrees("D-012 decisions")
    assert after.totals.departuresLost > before.totals.departuresLost
    print("baseline undecided / D-012:", before.totals.departuresLost, after.totals.departuresLost)
