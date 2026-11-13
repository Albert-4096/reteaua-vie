"""The generated public notice (D-013) on the three prepared cases, real data.

The stored cases are only read: the "final" hero notice applies the D-012 clerk
decisions (eval label 11067: tick the certain line 7 rows, untick the ring) to an
in-memory copy, or to a copy in a temp state dir for the API test.
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import pytest

from tests.conftest import DATA_DIR, needs_data

pytestmark = needs_data

HERO, E3, MOCIONI = "cl_20261108_16dec", "cl_20261107_e3", "cl_20261102_mocioni"
LABELS = Path(__file__).resolve().parents[2] / "eval" / "labels"
REAL_STATE = DATA_DIR / "state" / "closures"
CEDILLA = "şţŞŢ"  # s/t with cedilla: Romanian needs comma below (ș ț Ș Ț)


def _read(cid: str, part: str | None = None) -> dict:
    name = f"{cid}.json" if part is None else f"{cid}.{part}.json"
    return json.loads((REAL_STATE / name).read_text(encoding="utf-8"))


def _gold(post_id: int, route_id: str | None = None) -> tuple[set, set]:
    label = json.loads((LABELS / f"{post_id}.json").read_text(encoding="utf-8"))
    sure, unsure = set(), set()
    for a in label["gold"]["routeActions"]:
        if route_id and a["routeId"] != route_id:
            continue
        sure |= {(s, a["routeId"], a["directionId"]) for s in a["suspendedStopIds"]}
        unsure |= {(s, a["routeId"], a["directionId"]) for s in a["uncertainStopIds"]}
    return sure, unsure


def d012_decisions(analysis: dict) -> list[dict]:
    """D-012: tick the 21 certain line 7 rows, untick the 29 ring rows (eval label 11067)."""
    sure, ring = _gold(11067, "R_TV_7")
    out = []
    for r in analysis["stops"]:
        k = (r["stopId"], r["routeId"], r["directionId"])
        if r["state"] == "unsure" and (k in sure or k in ring):
            out.append({"stopId": r["stopId"], "routeId": r["routeId"], "directionId": r["directionId"],
                        "confirmed": k in sure})
    return out


def _case(cid: str, decisions: list[dict] | None = None):
    """(closure, analysis, impact) of a stored case; decisions go on an in-memory copy only."""
    from app.m1_disruption import analysis as an
    from app.m1_disruption import impact as imp
    from app.models.v1 import Analysis

    closure, analysis = _read(cid), copy.deepcopy(_read(cid, "analysis"))
    rows = analysis["stops"]
    if decisions:
        by_key = {(d["stopId"], d["routeId"], d["directionId"]): d["confirmed"] for d in decisions}
        for r in rows:
            k = (r["stopId"], r["routeId"], r["directionId"])
            if k in by_key:
                r["confirmed"] = by_key[k]
        rows, _ = an.enrich(closure, rows)  # nearest served stops change with the decisions
        analysis["unsureCount"] = sum(1 for r in rows if r["state"] == "unsure" and r["confirmed"] is None)
    return closure, Analysis.model_validate(analysis), imp.build_impact(closure, rows)


def _notice(cid: str, decisions: list[dict] | None = None):
    from app.m1_disruption.notice_text import build_notice

    return build_notice(*_case(cid, decisions))


@pytest.fixture(scope="module")
def hero_draft():
    return _notice(HERO)


@pytest.fixture(scope="module")
def hero_final():
    return _notice(HERO, d012_decisions(_read(HERO, "analysis")))


def _all_text(n) -> str:
    return n.text.ro + "\n" + (n.text.en or "")


def test_hero_draft_lists_50_unsure_apart(hero_draft):
    n = hero_draft
    assert n.status == "draft" and n.unsureCount == 50
    assert n.text.ro.startswith("Ciornă: 50 de stații de confirmat")
    assert n.text.en.startswith("Draft: 50 stops to confirm")
    final_part, confirm_part = n.text.ro.split("De confirmat", 1)
    # the unsure line 7 rows are never in the final lists
    assert not any(s.routeId == "R_TV_7" for s in n.sections)
    assert "Linia 7" not in final_part and "Linia 7 (tramvai), în sensul spre" in confirm_part
    assert "Banatul" in confirm_part
    assert "Linia 4 (tramvai) nu circulă." in final_part


def test_hero_final_with_d012_decisions(hero_final):
    n = hero_final
    assert n.status == "final" and n.unsureCount == 0
    assert "Ciornă" not in n.text.ro and "De confirmat" not in n.text.ro
    sure, ring = _gold(11067, "R_TV_7")
    listed = {(s.stopId, sec.routeId, sec.directionId) for sec in n.sections if sec.routeId == "R_TV_7"
              for s in sec.stopsNotServed}
    assert listed == sure and len(sure) == 21
    assert not listed & ring
    # line 4: whole line, one sentence, no stop list in the text (the JSON keeps the stops)
    line4 = [sec for sec in n.sections if sec.routeId == "R_TV_4"]
    assert len(line4) == 1 and line4[0].directionId is None and line4[0].action == "suspended"
    assert "Linia 4 (tramvai) nu circulă." in n.text.ro
    assert "Line 4 (tram) is not running." in n.text.en
    # every stop of lines 2 and 7 is named with its nearest served stop or the lines that still serve it
    nearest: dict[str, object] = {}  # per stop: the closest served stop over the lines that lose it
    for sec in n.sections:
        if sec.routeId == "R_TV_4":
            continue
        for s in sec.stopsNotServed:
            assert f"– {s.name}" in n.text.ro
            ns = s.nearestServed
            if ns and ns.stopId != s.stopId and (s.stopId not in nearest
                                                 or ns.distanceMeters < nearest[s.stopId].distanceMeters):
                nearest[s.stopId] = ns
    for ns in nearest.values():
        assert ns.name in n.text.ro and ns.distanceMeters <= 1500 * 1.3
    # lines 2 and 7 lose the same stops: one block, the common stops once for both directions
    assert "Liniile 2 și 7 (tramvai) circulă pe trasee scurtate.\nÎn ambele sensuri, nu opresc în:" in n.text.ro
    assert n.text.ro.count("– Mendeleev.") == 1
    assert "În sensul spre Shopping City / Bulevardul Dâmbovița, nu opresc nici în:" in n.text.ro
    # sections keep the full per-line, per-direction detail
    assert {(sec.routeId, sec.directionId) for sec in n.sections} == {
        ("R_TV_4", None), ("R_TV_2", 0), ("R_TV_2", 1), ("R_TV_7", 0), ("R_TV_7", 1)}
    _, _, impact = _case(HERO, d012_decisions(_read(HERO, "analysis")))
    assert len(n.stopsWithNoService) == impact.totals.stopsSuspended
    assert "Stații în care nu oprește niciun mijloc de transport" in n.text.ro
    assert "Linie temporară: autobuzul 4b, pe traseul Piața Iuliu Maniu – " in n.text.ro
    assert [t.shortName for t in n.temporaryRoutes] == ["4b"]
    assert n.text.ro.startswith("Duminică, 8 noiembrie 2026, între orele 10:00 și 18:00.")
    assert n.text.ro.rstrip().endswith(f"/a/{HERO}") and n.mapUrl.endswith(f"/a/{HERO}")
    assert n.sourceText and n.sourceUrl and "stpt.ro" in n.sourceUrl


def _fresh(cid: str) -> tuple[dict, list[dict]]:
    """The stored rows re-enriched in memory, as `make precompute` stores them."""
    from app.m1_disruption import analysis as an

    closure, analysis = _read(cid), copy.deepcopy(_read(cid, "analysis"))
    rows, _ = an.enrich(closure, analysis["stops"])
    return closure, rows


def _built(closure: dict, rows: list[dict]):
    from app.m1_disruption import impact as imp
    from app.m1_disruption.notice_text import build_notice
    from app.models.v1 import Analysis

    analysis = dict(_read(closure["id"], "analysis"), stops=rows)
    return build_notice(closure, Analysis.model_validate(analysis), imp.build_impact(closure, rows))


def test_hero_draft_never_offers_the_undecided_line_7():
    """T3: before any decision every line 7 row is undecided, so line 7 is never a stop's alternative."""
    import re

    from app.m1_disruption import impact as imp

    closure, rows = _fresh(HERO)
    assert all(imp.is_undecided(r) for r in rows if r["routeId"] == "R_TV_7")
    undecided = {(r["stopId"], r["routeId"]) for r in rows if imp.is_undecided(r)}
    for r in rows:  # the nearest served stop never relies on an undecided row (890, kept, still counts)
        ns = r["nearestServed"] or {}
        assert not any((ns.get("stopId"), rid) in undecided for rid in ns.get("routeIds") or []), r
    for n in (_built(closure, rows), _notice(HERO)):  # fresh, and as stored now
        assert n.status == "draft"
        for text, cut in ((n.text.ro, "De confirmat"), (n.text.en, "To confirm")):
            final_part = text.split(cut)[0]
            assert not re.search(r"\b7\b", final_part), final_part
        # the stops with no service are still the impact's: undecided rows count only after a decision
        assert len(n.stopsWithNoService) == imp.build_impact(closure, rows).totals.stopsSuspended
    # the only line left at a stop is undecided and no sure stop is known: „de confirmat”, not the line
    no_near = copy.deepcopy(rows)
    for r in no_near:
        if r["stopId"] in ("85", "86"):  # Catedrala Mitropolitană, both sides
            r["nearestServed"] = None
    n = _built(closure, no_near)
    assert re.search(r"– Catedrala Mitropolitană[^\n]*\. Alternativa: de confirmat\.", n.text.ro)
    assert re.search(r"– Catedrala Mitropolitană[^\n]*\. Alternative: to be confirmed\.", n.text.en)


def test_notice_and_analysis_give_the_same_walking_distances():
    """T13: one figure per nearest served stop (10 m steps) in the rows, the JSON and the text;
    a stop with no service carries the nearest served stop of its rows."""
    for cid in (HERO, E3, MOCIONI):
        closure, rows = _fresh(cid)
        n = _built(closure, rows)
        dists = {(r["stopId"], r["nearestServed"]["stopId"]): r["nearestServed"]["distanceMeters"]
                 for r in rows if r["nearestServed"]}
        assert all(d % 10 == 0 for d in dists.values())
        for sec in n.sections:
            for s in sec.stopsNotServed:
                ns = s.nearestServed
                if ns and ns.stopId != s.stopId:
                    assert ns.distanceMeters == dists[(s.stopId, ns.stopId)]
                    if sec.routeId != "R_TV_4":  # whole line 4: the text has no stop list
                        assert f"{int(ns.distanceMeters)}" in n.text.ro
        assert n.stopsWithNoService or cid == MOCIONI  # Mocioni: other lines stop everywhere
        for s in n.stopsWithNoService:
            known = [r["nearestServed"]["distanceMeters"] for r in rows
                     if r["stopId"] == s.stopId and r["nearestServed"] and r["nearestServed"]["stopId"] != s.stopId]
            assert s.nearestServed is not None and s.nearestServed.distanceMeters == min(known), (cid, s)


def test_e3_and_mocioni_have_nothing_undecided():
    """T3 changes only notices with undecided rows, so E3 and Mocioni keep their text."""
    from app.m1_disruption import impact as imp

    for cid in (E3, MOCIONI):
        closure, rows = _fresh(cid)
        assert not any(imp.is_undecided(r) for r in rows)
        assert "de confirmat" not in _built(closure, rows).text.ro


def test_hero_same_name_stops_do_not_contradict(hero_final):
    """A name shared by a served and a not-served stop is qualified with the mode and the lines."""
    from app.m1_disruption.notice_text import _service, _Text

    closure, analysis, impact = _case(HERO, d012_decisions(_read(HERO, "analysis")))
    n = hero_final
    ro = n.text.ro
    assert "– Catedrala Mitropolitană (stația de tramvai). Cea mai apropiată stație deservită: " \
           "Catedrala Mitropolitană (stația autobuzelor 32, 33, 33b și E3)" in ro
    no_service = ro.split("Stații în care nu oprește niciun mijloc de transport în comun în acest interval: ")[1]
    assert no_service.startswith("Catedrala Mitropolitană (stația de tramvai), ")
    assert "Piața Sfânta Maria (16 Decembrie 1989) (stația de tramvai" in no_service
    assert "Piața Sfânta Maria (16 Decembrie 1989) (stația tramvaielor " in ro
    # generic: no stop label is used both for a served stop and for a stop with no service
    rows = [r.model_dump(mode="json") for r in analysis.stops]
    svc = _service(closure, rows)
    ctx = _Text(closure, rows, n.sections, n.stopsWithNoService, svc)
    unserved = {ctx.no_service_label(s.stopId, "ro") for s in n.stopsWithNoService}
    named = [s for sec in n.sections if sec.routeId != "R_TV_4" for s in sec.stopsNotServed]  # line 4: no list
    same_name = {str(s["id"]) for s in ctx.net.stops if s["name"] in {x.name for x in n.stopsWithNoService}}
    served = {ctx.served_label(sid, "ro") for sid in {s.stopId for s in named} | same_name
              | {s.nearestServed.stopId for s in named if s.nearestServed} if ctx.remaining(sid)}
    assert not unserved & served
    # E3 has no such clash: no qualifier is added
    assert "(stația" not in _notice(E3).text.ro


def test_e3_names_the_11_suspended_stops_of_notice_11065():
    n = _notice(E3)
    sure, _ = _gold(11065)
    listed = {(s.stopId, sec.routeId, sec.directionId) for sec in n.sections for s in sec.stopsNotServed}
    assert listed == sure and len(sure) == 11
    heads = {sec.directionId: (sec.headsign, len(sec.stopsNotServed)) for sec in n.sections}
    assert heads == {0: ("ELBA", 6), 1: ("Apicultorilor", 5)}
    assert n.status == "final"
    # the 5 stops both directions lose are listed once, then the one extra stop towards ELBA
    assert "Linia E3 (autobuz) circulă pe un traseu deviat.\nÎn ambele sensuri, nu oprește în:" in n.text.ro
    assert "În sensul spre ELBA, nu oprește nici în:\n– Baba Novac." in n.text.ro
    assert n.text.ro.count("– ") == 6
    for sec in n.sections:
        for s in sec.stopsNotServed:
            assert s.nearestServed is not None
            assert s.nearestServed.name in n.text.ro
    assert n.text.ro.startswith("De sâmbătă, 7 noiembrie 2026, ora 04:00, până joi, 12 noiembrie 2026, ora 24:00.")
    assert len(n.stopsWithNoService) == 11  # E3 is the only line on those stops


def test_mocioni_names_the_lost_stops():
    from app.common.city import load_network

    n = _notice(MOCIONI)
    net = load_network()
    named = {s.stopId for sec in n.sections for s in sec.stopsNotServed}
    assert {"353", "354", "356", "357", "291"} <= named
    for sid in named:
        assert net.stop_by_id[sid]["name"] in n.text.ro
    assert "Stația rămâne deservită de autobuzele" in n.text.ro   # other lines still stop there
    assert n.text.ro.startswith("Începând de luni, 2 noiembrie 2026, până la finalizarea lucrărilor.")


def test_whole_line_phrasing_follows_the_decisions():
    from app.m1_disruption.notice_text import build_notice

    closure, analysis, impact = _case(HERO)
    # the whole line, one direction only
    one_dir = copy.deepcopy(closure)
    for a in one_dir["routeActions"]:
        if a["routeId"] == "R_TV_4":
            a["directionId"] = 0
    n = build_notice(one_dir, analysis, impact)
    assert "Linia 4 (tramvai) nu circulă în sensul spre Piața Gh. Domășneanu." in n.text.ro
    assert "Linia 4 (tramvai) nu circulă." not in n.text.ro
    # a person unticks one line 4 row: no longer the whole line, so the stops are listed
    a2 = analysis.model_copy(deep=True)
    row = next(r for r in a2.stops if r.routeId == "R_TV_4")
    row.confirmed = False
    n2 = build_notice(closure, a2, impact)
    assert "Linia 4 (tramvai) nu circulă." not in n2.text.ro
    assert "Linia 4 (tramvai) nu circulă pe o porțiune a traseului." in n2.text.ro
    listed = {(s.stopId, sec.directionId) for sec in n2.sections if sec.routeId == "R_TV_4" for s in sec.stopsNotServed}
    assert (row.stopId, row.directionId) not in listed
    assert len(listed) == sum(1 for r in a2.stops if r.routeId == "R_TV_4") - 1


def test_romanian_letters_use_comma_below(hero_final, hero_draft):
    for n in (hero_final, hero_draft, _notice(E3), _notice(MOCIONI)):
        body = json.dumps(n.model_dump(mode="json"), ensure_ascii=False)
        assert not any(ch in body for ch in CEDILLA)
    assert "ț" in hero_final.text.ro and "ș" in hero_final.text.ro


def test_build_notice_is_pure():
    from app.m1_disruption.notice_text import build_notice

    closure, analysis, impact = _case(HERO)
    before = (copy.deepcopy(closure), analysis.model_dump(), impact.model_dump())
    first = build_notice(closure, analysis, impact)
    assert (closure, analysis.model_dump(), impact.model_dump()) == before
    assert build_notice(closure, analysis, impact) == first


def test_api_notice_draft_and_timing(client):
    for cid in (HERO, E3, MOCIONI):  # warm the impact caches once (Mocioni loads GTFS 4.29 cold: ~10 s)
        client.get(f"/api/closures/{cid}/notice")
    for cid in (HERO, E3, MOCIONI):
        t0 = time.perf_counter()
        r = client.get(f"/api/closures/{cid}/notice")
        took = time.perf_counter() - t0
        assert r.status_code == 200, r.text
        assert took < 1.0, f"{cid}: {took:.2f} s"
    body = client.get(f"/api/closures/{HERO}/notice").json()
    assert body["status"] == "draft" and body["unsureCount"] == 50
    assert client.get("/api/closures/nope/notice").json()["error"]["code"] == "NOT_FOUND"
    # the hero stays `analyzed` with no decisions (D-011); E3 and Mocioni may be pre-published (T4)
    assert _read(HERO)["status"] == "analyzed"
    assert not (REAL_STATE / f"{HERO}.decisions.json").exists()


def test_api_notice_final_after_decisions(client, isolated_state):
    from app.common import state
    from app.models.v1 import Analysis
    from app.m1_disruption.notice_text import GeneratedNotice

    analysis = _read(HERO, "analysis")
    state.write("closures", HERO, _read(HERO))
    state.write("closures", HERO, Analysis.model_validate(analysis), part=state.PART_ANALYSIS)
    r = client.patch(f"/api/closures/{HERO}/stops", json={"decisions": d012_decisions(analysis)})
    assert r.status_code == 200, r.text
    body = client.get(f"/api/closures/{HERO}/notice").json()
    n = GeneratedNotice.model_validate(body)
    assert n.status == "final" and n.unsureCount == 0
    assert n.text.ro == _notice(HERO, d012_decisions(analysis)).text.ro
