"""The notice parser, the prepared cases and precompute, on the real STPT notices (SPEC §6.1.3, §5, §10)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from shapely.geometry import shape

from app import config
from app.common.geo import length_m
from app.config import TZ
from conftest import DATA_DIR, needs_data

pytestmark = needs_data

REPO = Path(__file__).resolve().parents[2]
LABELS = REPO / "eval" / "labels"
POSTS = {"hero": 11067, "e3": 11065, "mocioni": 11060, "polona": 11062, "m30": 11058}


def _post(pid: int):
    from app.common.stpt_posts import get_post

    p = get_post(pid)
    if p is None:
        pytest.skip(f"STPT post {pid} not recorded")
    return p


def _parse(pid: int):
    from app.m1_disruption.parser import parse_detail

    p = _post(pid)
    return parse_detail(p.text, reference=p.date)


def _actions(d) -> dict:
    return {(a.routeId, a.directionId): a for a in d.closure.routeActions or []}


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    """A DATA_DIR that links every real entry except state/ (closures written here stay in tmp)."""
    for p in DATA_DIR.iterdir():
        if p.name != "state":
            (tmp_path / p.name).symlink_to(p)
    real = config.get_settings()
    fake = config.Settings(env_file=None, data_dir=tmp_path, live_dir=real.live_dir, demo_now=real.demo_now,
                           data_freeze=False, public_base_url=real.public_base_url)
    monkeypatch.setattr(config, "get_settings", lambda: fake)
    import app.common.state as state_mod

    monkeypatch.setattr(state_mod, "get_settings", lambda: fake)
    config.ensure_dirs(fake)
    return fake


# --- text helpers ------------------------------------------------------------------------


def test_norm_folds_diacritics_dots_and_abbreviations():
    from app.m1_disruption.parser import norm

    assert norm("Canton C.F.R.") == norm("Canton CFR") == "canton cfr"
    assert norm("b-dul Constantin Brâncoveanu") == "bulevardul constantin brancoveanu"
    assert norm("Str. Dr. Iosif Nemoianu") == "strada doctor iosif nemoianu"
    assert norm("Bulevardului 16 Decembrie 1989") == "bulevardul 16 decembrie 1989"
    assert norm("Șagului") == norm("Şagului") == "sagului"   # comma-below and cedilla


def test_sentences_keep_initials_together():
    from app.m1_disruption.parser import split_sentences

    s = split_sentences("Stațiile deservite: C. Brâncoveanu, V. Simionescu și B.A.T.M. Linia M46 circulă.")
    assert s == ["Stațiile deservite: C. Brâncoveanu, V. Simionescu și B.A.T.M.", "Linia M46 circulă."]


def test_window_rules():
    from app.m1_disruption.parser import window_from

    ref = datetime(2026, 11, 3, 19, 0, tzinfo=TZ)
    w = window_from("în data de 8 noiembrie 2026, în intervalul orar 10 00 – 18 00, pe Bd. 16 Decembrie 1989", ref)
    assert (w.start.isoformat(), w.end.isoformat()) == ("2026-11-08T10:00:00+02:00", "2026-11-08T18:00:00+02:00")
    w = window_from("în perioada 07 noiembrie 2026, ora 04:00 – 12 noiembrie 2026, ora 24:00", ref)
    assert w.end.isoformat() == "2026-11-13T00:00:00+02:00"   # 24:00 rolls to the next day
    w = window_from("Începând de mâine, linia Expres 3 își reia circulația", ref)
    assert w.start.isoformat() == "2026-11-04T00:00:00+02:00" and w.open_end
    assert window_from("pe Bulevardul 16 Decembrie 1989 și Str. 1 Decembrie 1918", ref) is None


def test_line_tokens():
    from app.m1_disruption.parser import line_tokens

    assert line_tokens("traseul Liniei Expres 3 va fi modificat") == ["e3"]
    assert line_tokens("liniilor metropolitane M 32, M36, M37 și M51 S8") == ["m32", "m36", "m37", "m51", "s8"]
    assert line_tokens("introduce temporar linia de autobuz 4b") == ["4b"]


# --- the five real notices -----------------------------------------------------------------


def test_e3_notice_11065():
    d = _parse(POSTS["e3"])
    c = d.closure
    assert c.routeIds == ["R_AB_E3"]
    assert (c.window.start, c.window.end) == ("2026-11-07T04:00:00+02:00", "2026-11-13T00:00:00+02:00")
    a = _actions(d)
    assert a[("R_AB_E3", 0)].action == "rerouted"
    assert a[("R_AB_E3", 0)].suspendedStopIds == ["335", "336", "337", "338", "339", "340"]   # către Elba
    assert a[("R_AB_E3", 1)].suspendedStopIds == ["318", "319", "320", "321", "322"]          # către Apicultorilor
    assert [s.name for s in d.section] == ["Strada Rahovei", "Strada Martir Gogu Opre"]
    g = shape(c.geometry.model_dump())
    assert 200 < length_m(g) < 1500          # a section of Str. Ardealului, not the whole street
    assert d.unread == []
    assert d.cause == "CONSTRUCTION"


def test_hero_notice_11067():
    d = _parse(POSTS["hero"])
    c = d.closure
    assert (c.window.start, c.window.end) == ("2026-11-08T10:00:00+02:00", "2026-11-08T18:00:00+02:00")
    assert set(c.routeIds) == {"R_TV_4", "R_TV_2", "R_TV_7"}
    a = _actions(d)
    assert a[("R_TV_4", None)].action == "suspended"
    keep2 = a[("R_TV_2", 0)].keepStopIds
    assert a[("R_TV_2", 0)].action == "shortened" and keep2[0] == "13" and keep2[-1] == "59"  # Shopping City .. Piața Maria
    assert a[("R_TV_7", 0)].keepStopIds == ["890"]                                          # Depou Dâmbovița
    assert d.tram and d.cause == "MAINTENANCE"
    (t,) = c.temporaryRoutes
    assert t.shortName == "4b" and t.mode == "bus" and t.stopIds is None and len(t.streets) == 8
    assert length_m(shape(t.geometry.model_dump())) > 3000
    for u in d.unread:                    # unread sentences are verbatim pieces of the notice
        assert u in _post(POSTS["hero"]).text


def test_mocioni_notice_11060_reads_served_lists():
    d = _parse(POSTS["mocioni"])
    assert set(d.closure.routeIds) == {"R_AB_M32", "R_AB_M36", "R_AB_M37", "R_AB_M38", "R_AB_M46", "R_AB_M51"}
    assert "s8" in d.lines_unknown                 # S8 is not in the GTFS
    assert d.window.open_end
    by = {(s["routeId"], s["directionId"]): s for s in d.served_lists}
    assert by[("R_AB_M32", 0)]["openSide"] == "end" and by[("R_AB_M32", 1)]["openSide"] == "start"
    assert len(by[("R_AB_M36", 0)]["names"]) == 13
    for a in d.closure.routeActions:
        assert a.stopNames is None                 # served names are never sent as suspended names


def test_no_closure_notices_give_no_suspended_stops():
    m30 = _parse(POSTS["m30"])
    assert not any(a.suspendedStopIds for a in m30.closure.routeActions or [])
    assert any("prelungit" in u for u in m30.unread)          # an extension is not mapped: listed for review
    pol = _parse(POSTS["polona"])
    assert {a.routeId for a in pol.closure.routeActions} == {"R_AB_E3"}
    assert all(a.suspendedStopIds == [] for a in pol.closure.routeActions)


def _rows(closure) -> set:
    from app.common import gtfs

    rows = set()
    for a in closure.routeActions or []:
        for d in ([a.directionId] if a.directionId is not None else [0, 1]):
            order = gtfs.stop_order(a.routeId, d)
            if a.action == "suspended":
                ids = order
            elif a.action == "shortened":
                ids = [s for s in order if s not in set(a.keepStopIds or [])]
            else:
                ids = a.suspendedStopIds or []
            rows |= {(s, a.routeId, d) for s in ids}
    return rows


@pytest.mark.skipif(not LABELS.is_dir(), reason="no eval labels")
@pytest.mark.parametrize("pid", list(POSTS.values()))
def test_against_eval_labels(pid):
    """Rows (stop, route, direction) from the parser's actions vs the eval gold; uncertain rows ignored."""
    label = json.loads((LABELS / f"{pid}.json").read_text(encoding="utf-8"))
    pos, ignore = set(), set()
    for a in label["gold"]["routeActions"]:
        pos |= {(s, a["routeId"], a["directionId"]) for s in a["suspendedStopIds"]}
        ignore |= {(s, a["routeId"], a["directionId"]) for s in a["uncertainStopIds"]}
    pred = _rows(_parse(pid).closure) - ignore
    assert pred - pos == set(), f"false positives {sorted(pred - pos)[:10]}"
    assert pos - pred == set(), f"missed {sorted(pos - pred)[:10]}"


# --- API ---------------------------------------------------------------------------------


def test_parse_endpoint_saves_a_draft(state_dir):
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    r = c.post("/api/closures/parse", json={"text": _post(POSTS["e3"]).text})
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"closure", "unread"}
    cl = body["closure"]
    assert cl["status"] == "draft" and cl["kind"] == "notice" and cl["id"].startswith("cl_")
    assert c.get(f"/api/closures/{cl['id']}").json()["routeActions"] == cl["routeActions"]
    assert c.post("/api/closures/parse", json={"text": "   "}).json()["error"]["code"] == "INVALID_INPUT"
    assert c.post("/api/closures/parse", json={}).status_code == 422


# --- prepared cases and precompute ---------------------------------------------------------------


def test_build_cases():
    from app.cases.build import build_all
    from app.cases.catalog import CASES_BY_ID

    built = {b.closure.id: b for b in build_all(save=False)}
    hero = built["cl_20261108_16dec"].closure
    assert hero.direction == "along" and hero.geometry.type == "LineString"
    assert 200 < length_m(shape(hero.geometry.model_dump())) < 1500
    assert hero.window.start == CASES_BY_ID["case_16dec"].window_start
    assert hero.sourceUrl.startswith("https://stpt.ro/") and "linia 4 va fi suspendată" in hero.sourceText
    assert built["cl_20261108_16dec"].approximate and not built["cl_20261107_e3"].approximate
    moc = {(a.routeId, a.directionId): a.suspendedStopIds for a in built["cl_20261102_mocioni"].closure.routeActions}
    assert moc[("R_AB_M32", 0)] == ["356", "357", "291"]       # GTFS 4.29 normal pattern (SPEC §5.3)
    assert moc[("R_AB_M38", 0)] == []                          # M38 keeps its stops


def test_precompute_is_idempotent_and_never_publishes(state_dir):
    from app import precompute
    from app.common import state

    first = precompute.prepare_cases()
    snap = {p.name: p.read_bytes() for p in (state_dir.state_dir / "closures").glob("*.json")}
    second = precompute.prepare_cases()
    assert {r["id"]: r["status"] for r in first} == {r["id"]: "analyzed" for r in first}
    assert [r["rows"] for r in first] == [r["rows"] for r in second]
    assert {p.name: p.read_bytes() for p in (state_dir.state_dir / "closures").glob("*.json")} == snap
    assert state.list_ids("published") == []
