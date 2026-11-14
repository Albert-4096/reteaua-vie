"""The demo reset undoes Publish and nothing else (decisions, analysis and impact stay)."""

from __future__ import annotations

import json

import pytest

from tests.conftest import DATA_DIR, needs_data
from tests.test_m1_notice_text import d012_decisions

pytestmark = needs_data

HERO = "cl_20261108_16dec"
REAL = DATA_DIR / "state" / "closures"


def _read(part: str | None = None) -> dict:
    name = f"{HERO}.json" if part is None else f"{HERO}.{part}.json"
    return json.loads((REAL / name).read_text(encoding="utf-8"))


def test_unpublish_takes_the_hero_back_and_keeps_the_decisions(client, isolated_state):
    from app.common import state
    from app.demo_reset import unpublish
    from app.models.v1 import Analysis

    analysis = _read("analysis")
    state.write("closures", HERO, {**_read(), "status": "analyzed"})
    state.write("closures", HERO, Analysis.model_validate(analysis), part=state.PART_ANALYSIS)
    assert client.patch(f"/api/closures/{HERO}/stops", json={"decisions": d012_decisions(analysis)}).status_code == 200
    decided = state.read("closures", HERO, state.PART_ANALYSIS)

    assert unpublish(HERO) == {"closureId": HERO, "wasPublished": False, "status": "analyzed"}  # nothing to undo yet

    assert client.post(f"/api/closures/{HERO}/publish").status_code == 200
    assert client.get(f"/api/closures/{HERO}").json()["status"] == "published"
    assert any(a["closureId"] == HERO for a in client.get("/api/feed/alerts.json").json())

    assert unpublish(HERO)["wasPublished"] is True
    assert client.get(f"/api/closures/{HERO}").json()["status"] == "analyzed"
    assert not any(a["closureId"] == HERO for a in client.get("/api/feed/alerts.json").json())
    assert not state.exists("published", HERO)
    assert state.read("closures", HERO, state.PART_ANALYSIS) == decided  # the person's answers are untouched
    assert client.get(f"/api/closures/{HERO}/notice").json()["status"] == "final"

    assert client.post(f"/api/closures/{HERO}/publish").status_code == 200  # and Publish works again


def test_unpublish_refuses_unknown_and_prepared_cases(isolated_state):
    from app.common import state
    from app.demo_reset import unpublish

    with pytest.raises(LookupError):
        unpublish("cl_nope")
    state.write("closures", "cl_x", {"id": "cl_x", "status": "published"})
    state.write("published", "cl_x", {"closureId": "cl_x", "alerts": [], "reconstructed": True})
    with pytest.raises(PermissionError):
        unpublish("cl_x")
    assert unpublish("cl_x", force=True)["wasPublished"] is True
    assert state.read("closures", "cl_x")["status"] == "analyzed"


def test_reset_removes_added_works_and_never_a_prepared_one(isolated_state):
    from app.common import state
    from app.demo_reset import SEEDED, remove_added_works

    def cache(sub: str, name: str):
        path = isolated_state.cache_dir / sub / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
        return path

    assert set(SEEDED) == {"cl_20261102_mocioni", "cl_20261107_e3", HERO}
    for cid in SEEDED:
        state.write("closures", cid, {"id": cid, "status": "published"})
        state.write("closures", cid, {"stops": []}, part=state.PART_ANALYSIS)
        state.write("published", cid, {"closureId": cid, "alerts": []})
        state.write("scenarios", f"s0_{cid}", {"id": f"s0_{cid}"})
        state.write("scans", cid, {"scans": []})
    kept_cache = [cache("detour", f"{SEEDED[1]}_abc.json"), cache("r5/gtfs", f"patched_{HERO}_1.zip"), cache("jobs", "0a1b2c.json")]
    state.write("scenarios", "sp_16dec_1_l7_pr", {"id": "sp_16dec_1_l7_pr"})  # a prepared scenario with no closure id in its name

    draft = "cl_20261115_0145_bfbb5b"   # the id shape POST /api/closures/parse gives
    state.write("closures", draft, {"id": draft, "status": "published"})
    state.write("closures", draft, {"stops": []}, part=state.PART_ANALYSIS)
    state.write("closures", draft, {"totals": {}}, part=state.PART_IMPACT)
    state.write("published", draft, {"closureId": draft, "alerts": []})
    state.write("published", draft, {"ok": True}, part="validation")
    state.write("scenarios", f"s0_{draft}", {"id": f"s0_{draft}"})
    state.write("scans", draft, {"scans": []})
    gone_cache = [cache("detour", f"{draft}_abc.json"), cache("r5/gtfs", f"patched_{draft}_1.zip"), cache("posters", f"{draft}_S1.pdf")]

    assert remove_added_works() == [draft]

    assert not [p for p in isolated_state.data_dir.rglob("*") if draft in p.name]   # no file of the draft is left
    assert not any(p.exists() for p in gone_cache)
    assert state.list_ids("closures") == sorted(SEEDED)
    assert state.list_ids("published") == sorted(SEEDED)
    assert state.list_ids("scans") == sorted(SEEDED)
    assert state.list_ids("scenarios") == sorted([*(f"s0_{c}" for c in SEEDED), "sp_16dec_1_l7_pr"])
    for cid in SEEDED:
        assert state.exists("closures", cid, state.PART_ANALYSIS)
    assert all(p.exists() for p in kept_cache)
    assert remove_added_works() == []   # nothing left to remove; the prepared works are still there
    assert state.list_ids("closures") == sorted(SEEDED)


def test_reset_leaves_a_work_alone_when_its_id_overlaps_a_prepared_one(isolated_state):
    from app.common import state
    from app.demo_reset import remove_added_works

    for cid in (HERO, f"{HERO}_copy", "x_not_a_closure"):
        state.write("closures", cid, {"id": cid, "status": "draft"})
    assert remove_added_works() == []   # a glob on "<HERO>_copy" or on an odd id could reach the hero's files
    assert state.exists("closures", HERO)
