"""T2: the unsure rows of a closure come as a few questions (Analysis.decisionGroups), real data.

The hero case (notice 11067) has 50 unsure line 7 rows. The groups are derived from the
timetable only; the eval label of 11067 (D-012) is read here, in the test, to check them.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import DATA_DIR, needs_data

pytestmark = needs_data

HERO = "cl_20261108_16dec"
LABELS = Path(__file__).resolve().parents[2] / "eval" / "labels"
REAL_STATE = DATA_DIR / "state" / "closures"


def _read(cid: str, part: str | None = None) -> dict:
    name = f"{cid}.json" if part is None else f"{cid}.{part}.json"
    return json.loads((REAL_STATE / name).read_text(encoding="utf-8"))


def _gold_11067() -> tuple[set, set]:
    label = json.loads((LABELS / "11067.json").read_text(encoding="utf-8"))
    sure, ring = set(), set()
    for a in label["gold"]["routeActions"]:
        if a["routeId"] == "R_TV_7":
            sure |= {(s, a["routeId"], a["directionId"]) for s in a["suspendedStopIds"]}
            ring |= {(s, a["routeId"], a["directionId"]) for s in a["uncertainStopIds"]}
    return sure, ring


def _keys(rows) -> set:
    return {(r.stopId, r.routeId, r.directionId) for r in rows}


def test_hero_50_unsure_rows_are_two_questions():
    from app.m1_disruption.analysis import decision_groups

    rows = _read(HERO, "analysis")["stops"]
    for r in rows:
        r["confirmed"] = None  # as at the demo start
    groups = decision_groups(_read(HERO), rows)
    unsure = {(r["stopId"], r["routeId"], r["directionId"]) for r in rows if r["state"] == "unsure"}
    assert len(unsure) == 50 and 1 <= len(groups) <= 3
    covered = [k for g in groups for k in _keys(g.rows)]
    assert len(covered) == len(set(covered)) and set(covered) == unsure   # every unsure row exactly once
    assert len({g.id for g in groups}) == len(groups)
    # the split the data gives is the D-012 one: certain loss Catedrala – Calea Torontalului (+ 61), the ring open
    sure, ring = _gold_11067()
    by_id = {g.id: g for g in groups}
    lost, open_ = by_id["R_TV_7-lost"], by_id["R_TV_7-open"]
    assert lost.suggested == "affected" and _keys(lost.rows) == sure and len(sure) == 21
    assert open_.suggested is None and _keys(open_.rows) == ring and len(ring) == 29
    assert "Gara de Nord" in lost.reason.ro and "Tramvaiele 2 și 4" in lost.reason.ro
    assert open_.question.ro == "Oprește tramvaiul 7 între Banatul și Piața Sfânta Maria (Gheorghe Doja)?"
    for g in groups:
        assert g.question.ro.endswith("?") and g.question.en.endswith("?") and g.reason.en


def test_closures_with_no_unsure_rows_have_no_groups():
    from app.m1_disruption.analysis import decision_groups

    for cid in ("cl_20261107_e3", "cl_20261102_mocioni"):
        rows = _read(cid, "analysis")["stops"]
        assert not any(r["state"] == "unsure" for r in rows)
        assert decision_groups(_read(cid), rows) == []


def test_api_answers_one_group_with_the_existing_patch(client, isolated_state):
    from app.common import state
    from app.models.v1 import Analysis

    stored = _read(HERO, "analysis")
    stored.pop("decisionGroups", None)   # stored before the groups existed: GET adds them
    state.write("closures", HERO, _read(HERO))
    state.write("closures", HERO, Analysis.model_validate(stored), part=state.PART_ANALYSIS)
    a = client.get(f"/api/closures/{HERO}/analysis").json()
    groups = {g["id"]: g for g in a["decisionGroups"]}
    assert set(groups) == {"R_TV_7-lost", "R_TV_7-open"}
    # one click per group: the lost one as suggested, the ring as „still stops” (the D-012 answers)
    decisions = [{**k, "confirmed": True} for k in groups["R_TV_7-lost"]["rows"]]
    decisions += [{**k, "confirmed": False} for k in groups["R_TV_7-open"]["rows"]]
    r = client.patch(f"/api/closures/{HERO}/stops", json={"decisions": decisions})
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["unsureCount"] == 0
    assert {g["id"]: g["rows"] for g in after["decisionGroups"]} == {k: g["rows"] for k, g in groups.items()}
    assert client.get(f"/api/closures/{HERO}/analysis").json() == after
    sure, _ = _gold_11067()
    lost = {(s["stopId"], s["routeId"], s["directionId"]) for s in after["stops"]
            if s["routeId"] == "R_TV_7" and s["confirmed"] is True}
    assert lost == sure
