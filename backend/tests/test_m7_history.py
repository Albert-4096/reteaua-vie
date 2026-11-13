"""History: back-filled rows from the recorded STPT notices + closures published through the platform (SPEC §5.4)."""

from __future__ import annotations

import json

import pytest

from app.common import state
from app.common.stpt_posts import get_post
from app.models.v2 import HistoryEntry
from tests.conftest import DATA_DIR, needs_data

HERO, E3 = "cl_20261108_16dec", "cl_20261107_e3"


def _post(pid: int):
    p = get_post(pid)
    if p is None:
        pytest.skip(f"STPT post {pid} not recorded")
    return p


def _reasons(pid: int) -> list[str]:
    from app.m1_disruption import parser
    from app.m7_compliance.history import clean_reasons

    post = _post(pid)
    return clean_reasons(post, parser.parse_detail(post.text, post.date))


@needs_data
def test_clean_and_unclean_posts():
    assert _reasons(11065) == []          # E3, Ardealului: window + 6/5 suspended stops
    assert _reasons(11067) == []          # hero: line 4 suspended, 2 and 7 shortened, temporary 4b
    assert any("acțiune" in r for r in _reasons(10858))     # a campaign regulation, not a closure
    assert any("deservite" in r for r in _reasons(11060))   # Mocioni lists the served stops only


@needs_data
def test_backfill_rows_are_labelled_and_computed():
    from app.m7_compliance.history import NOTE_BACKFILLED, build_backfill

    bf = build_backfill()
    rows = {r.closureId: r for r in bf.entries}
    assert {"stpt_11065", "stpt_11067"} <= set(rows)
    unread = {u.postId for u in bf.unread}
    assert not unread & {11065, 11067}
    assert len(rows) + len(unread) == len(set(rows) | unread)   # every post is in exactly one list
    for r in bf.entries:
        HistoryEntry.model_validate(r.model_dump(exclude={"note", "sourceUrl", "provenance"}))
        assert r.note == NOTE_BACKFILLED
        assert r.note.ro == "reconstituit din anunț STPT, nu publicat prin platformă"
        assert r.alertsCount is None
        assert r.provenance and r.provenance[0].source.startswith("STPT")
    e3 = rows["stpt_11065"]
    post = _post(11065)
    assert e3.publishedAt == post.date.isoformat(timespec="seconds")
    assert (e3.window.start, e3.window.end) == ("2026-11-07T04:00:00+02:00", "2026-11-13T00:00:00+02:00")
    assert e3.routeIds == ["R_AB_E3"]
    assert e3.stopsSuspended and e3.stopsSuspended > 0 and e3.departuresLost and e3.departuresLost > 0
    assert e3.sourceUrl == post.link


@needs_data
def test_platform_row_replaces_the_reconstructed_one(isolated_state):
    from app.m7_compliance.history import NOTE_PLATFORM, history

    src = DATA_DIR / "state" / "closures"
    if not (src / f"{HERO}.json").is_file():
        pytest.skip("hero case not prepared (run make precompute)")
    closure = json.loads((src / f"{HERO}.json").read_text(encoding="utf-8"))
    state.write("closures", HERO, {**closure, "status": "published"})
    impact = src / f"{HERO}.impact.json"
    if impact.is_file():
        state.write("closures", HERO, json.loads(impact.read_text(encoding="utf-8")), part="impact")
    alert = {"informedEntity": [{"routeId": "R_TV_4", "stopId": None, "directionId": None}]}
    state.write("published", HERO, {"closureId": HERO, "alerts": [alert, alert], "feedUrl": "x", "posters": [],
                                    "publishedAt": "2026-11-08T12:00:00+02:00"})
    rows = history("2026-11-08", "2026-11-08")
    ids = [r.closureId for r in rows]
    assert HERO in ids and "stpt_11067" not in ids   # same STPT notice: the platform row wins
    hero = rows[ids.index(HERO)]
    assert hero.alertsCount == 2 and hero.note == NOTE_PLATFORM
    assert hero.publishedAt == "2026-11-08T12:00:00+02:00"
    # E3 (7–13 Nov) overlaps 8 Nov too; nothing ends before `from` or starts after `to`
    assert "stpt_11065" in ids
    from app.common.timeutil import parse_iso

    later = history("2026-11-14", None)
    assert all(parse_iso(r.window.end) > parse_iso("2026-11-14T00:00:00+02:00") for r in later)
    assert "stpt_11065" not in [r.closureId for r in later]   # E3 ended on 13 Nov 00:00


def test_bad_bounds_are_rejected():
    from app.common.errors import ApiError
    from app.m7_compliance.history import history

    with pytest.raises(ApiError) as e:
        history("yesterday", None)
    assert e.value.status_code == 422
    with pytest.raises(ApiError):
        history("2026-11-10", "2026-11-01")
