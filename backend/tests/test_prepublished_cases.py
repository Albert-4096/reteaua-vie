"""T4: at the demo start E3 and Mocioni are published with their notices' decisions, the hero is not.

The real cases are built from the real notices in a temp state dir (the rest of $DATA_DIR is
linked in read-only), so step 0 of the demo (GET /api/overview) is not empty.
"""

from __future__ import annotations

import sys

import pytest

from app import config, precompute
from app.cases.catalog import CASES, CASES_BY_CLOSURE
from app.common.stpt_posts import get_post
from app.common.timeutil import parse_iso
from tests.conftest import needs_data
from tests.test_m1_outputs import outputs_state  # noqa: F401

HERO = "cl_20261108_16dec"
E3 = "cl_20261107_e3"
MOCIONI = "cl_20261102_mocioni"


def test_notice_decisions_confirm_what_the_notice_names():
    rows = [
        {"stopId": "1", "routeId": "R", "directionId": 0, "state": "affected",
         "reasons": ["ON_ROUTE_PATH", "NAMED_IN_NOTICE"]},
        {"stopId": "2", "routeId": "R", "directionId": 1, "state": "unsure",
         "reasons": ["ON_ROUTE_PATH", "NOT_NAMED_IN_NOTICE"]},
        {"stopId": "3", "routeId": "R", "directionId": 0, "state": "affected", "reasons": ["ON_ROUTE_PATH"]},
        {"stopId": "4", "routeId": "R", "directionId": 0, "state": "unsure", "reasons": ["NAMED_IN_NOTICE"]},
    ]
    got = {d["stopId"]: d["confirmed"] for d in precompute.notice_decisions({"stops": rows})}
    assert got == {"1": True, "2": False, "4": True}   # row 3 stays the model's call


def test_only_e3_and_mocioni_start_published():
    assert {c.closure_id for c in CASES if c.starts_published} == {E3, MOCIONI}


@pytest.fixture
def demo_state(tmp_path, monkeypatch):
    """A data dir that links every real data folder except `state`, which starts empty."""
    real = config.get_settings()
    for p in real.data_dir.iterdir():
        if p.name != "state":
            (tmp_path / p.name).symlink_to(p)
    fake = config.Settings(env_file=None, data_dir=tmp_path, live_dir=real.live_dir,
                           demo_now=real.demo_now, data_freeze=False,
                           public_base_url=real.public_base_url)
    # import first, so every `from app.config import get_settings` is patched here and restored after
    import app.cases.build  # noqa: F401
    import app.main  # noqa: F401

    original = config.get_settings
    for name, mod in list(sys.modules.items()):
        if name.startswith("app") and getattr(mod, "get_settings", None) is original:
            monkeypatch.setattr(mod, "get_settings", lambda: fake)
    config.ensure_dirs(fake)
    from app.m1_disruption import publish

    # prepare_cases publishes without threads; a thread here would outlive the temp dir
    monkeypatch.setattr(publish, "start_validation", lambda closure_id: pytest.fail("validator thread"))
    monkeypatch.setattr(publish, "start_audio", lambda closure_id: pytest.fail("audio thread"))
    yield fake


@needs_data
def test_precompute_publishes_e3_and_mocioni_and_fills_the_overview(demo_state):
    from app.common import state
    from app.overview.summary import overview

    rows = {r["id"]: r for r in precompute.prepare_cases(reset=True)}
    assert rows[HERO]["status"] == "analyzed"
    assert state.read("published", HERO) is None
    for cid in (E3, MOCIONI):
        assert rows[cid]["status"] == "published", rows[cid]
        pub = state.read("published", cid)
        post = get_post(CASES_BY_CLOSURE[cid].post_id)
        assert parse_iso(pub["publishedAt"]) == post.date        # dated at the STPT notice
        assert pub["alerts"] and pub["posters"]
        analysis = state.read("closures", cid, state.PART_ANALYSIS)
        assert analysis["unsureCount"] == 0
        assert all(r["confirmed"] is True for r in analysis["stops"] if "NAMED_IN_NOTICE" in r["reasons"])
    # Mocioni's posters point at the public QR page
    mocioni = state.read("published", MOCIONI)
    assert {a["url"] for a in mocioni["alerts"] if a["id"].startswith("al_20261102_mocioni_stop_")} >= {
        f"{demo_state.public_base_url}/a/{MOCIONI}?stop={p['stopId']}" for p in mocioni["posters"]}

    ov = overview(parse_iso("2026-11-08T12:00:00+02:00"))
    assert [c["id"] for c in ov["activeClosures"]] == [MOCIONI, E3]
    assert ov["ghostDeparturesToday"] and ov["ghostDeparturesToday"] > 0
    assert any(p["source"].startswith("SMTT GTFS") for p in ov["provenance"])

    # labelled as reconstructed wherever they appear; a live publish is never labelled
    from app.m1_disruption.api_core import get_closure
    from app.m7_compliance.history import platform_rows
    from app.overview.closures import summarize

    for cid in (E3, MOCIONI):
        day = get_post(CASES_BY_CLOSURE[cid].post_id).date.strftime("%d.%m.%Y")
        note = f"reconstituit: publicat în demo din anunțul STPT din {day}"
        assert state.read("published", cid)["reconstructedNote"]["ro"] == note
        c = get_closure(cid)
        assert c.reconstructed is True and c.reconstructedNote.ro == note
        s = summarize(state.read("closures", cid))
        assert s.reconstructed is True and s.reconstructedNote.ro == note
        assert next(r for r in platform_rows() if r.closureId == cid).note.ro == note
    assert get_closure(HERO).reconstructed is None and summarize(state.read("closures", HERO)).reconstructed is None
    assert [c["reconstructed"] for c in ov["activeClosures"]] == [True, True]

    # a second run keeps them published (and labelled) and does not publish the hero
    again = {r["id"]: r["status"] for r in precompute.prepare_cases(reset=False)}
    assert again == {HERO: "analyzed", E3: "published", MOCIONI: "published"}
    assert state.read("published", E3)["reconstructed"] is True


@needs_data
def test_a_live_publish_is_never_labelled_reconstructed(outputs_state, client):  # noqa: F811
    from app.overview.closures import summarize
    from tests.test_m1_outputs import CLOSURE_ID, _analysis, _closure, _store

    _store(_closure(), _analysis(unsure_decision=True))
    r = client.post(f"/api/closures/{CLOSURE_ID}/publish")
    assert r.status_code == 200, r.text
    assert r.json().get("reconstructed") is None
    assert client.get(f"/api/closures/{CLOSURE_ID}").json().get("reconstructed") is None
    from app.common import state

    assert summarize(state.read("closures", CLOSURE_ID)).reconstructed is None
