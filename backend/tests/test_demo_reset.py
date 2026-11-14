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
