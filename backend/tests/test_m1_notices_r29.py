"""Notice parser on the STPT notices a person pasted into step 1 (R29): 11062, 10868, 10851, 11033, 10878.

Each test reads the recorded notice text (never fetched here) and checks what the analysis gets.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app import config
from app.config import TZ
from conftest import DATA_DIR, needs_data

pytestmark = needs_data


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


def _matched(d) -> dict:
    """What /analyze gets: rows per (route, direction), on the closure as /parse saves it."""
    from app.m1_disruption import matching

    c = d.closure.model_dump(mode="json", by_alias=True)
    if c.get("geometry") is None and c.get("routeActions"):
        c["geometry"] = matching.geometry_from_actions(c["routeActions"])
    rows, _unresolved = matching.match_closure(c)
    out: dict = {"geometry": c.get("geometry")}
    for r in rows:
        out.setdefault((r["routeId"], r["directionId"]), set()).add(r["stopId"])
    return out


def _keys(m: dict) -> set:
    return {k for k in m if k != "geometry"}


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


# --- windows ---------------------------------------------------------------------------------


def test_window_across_midnight_and_day_ranges():
    from app.m1_disruption.parser import window_from

    ref = datetime(2026, 9, 11, 14, 0, tzinfo=TZ)
    w = window_from("luni, 14 septembrie 2026, între 20:30 și 01:00", ref)
    assert (w.start.isoformat(), w.end.isoformat()) == ("2026-09-14T20:30:00+03:00", "2026-09-15T01:00:00+03:00")
    w = window_from("în perioada 3–4 octombrie 2026, circulația mai multor mijloace", ref)
    assert (w.start.isoformat(), w.end.isoformat()) == ("2026-10-03T00:00:00+03:00", "2026-10-05T00:00:00+03:00")
    assert not w.timed


def test_10851_window_is_the_hours_in_the_text():
    """First sentence: „în seara zilei de luni, 14 septembrie”; second: „ora 20:30, până marți, 15 septembrie, ora 01:00”."""
    w = _parse(10851).window
    assert (w.start.isoformat(), w.end.isoformat()) == ("2026-09-14T20:30:00+03:00", "2026-09-15T01:00:00+03:00")


def test_10878_window_spans_both_event_days():
    """„în perioada 3–4 octombrie”, then „Sâmbătă … 06:00–24:00” and „Duminică … 04:00–17:30”."""
    w = _parse(10878).window
    assert (w.start.isoformat(), w.end.isoformat()) == ("2026-10-03T06:00:00+03:00", "2026-10-04T17:30:00+03:00")


# --- E3 on Strada Polonă ----------------------------------------------------------------------


def test_11062_e3_loses_its_polona_stops_not_other_lines():
    """„stațiile amplasate pe strada Polonă … nu vor mai fi utilizate pe traseul liniei Expres 3”.

    Read on the timetable in force before the change (4.30): E3's Polonă (Pasaj Freidorf) stops,
    the same ids SMTT removed from E3 in 4.30 -> 4.31 (eval/gold_gtfs_diff.py). E7 and M36 still
    stop there and are not in the notice."""
    m = _matched(_parse(11062))
    assert _keys(m) == {("R_AB_E3", 0), ("R_AB_E3", 1)}
    assert m[("R_AB_E3", 0)] == {"344"} and m[("R_AB_E3", 1)] == {"314"}


def test_10868_e3_named_stops_not_e7_m36():
    """„stațiile Kromberg și ELBA vor fi suspendate” (tur), „Stațiile ELBA, Rudolf Otto și Kromberg …” (retur)."""
    d = _parse(10868)
    m = _matched(d)
    assert {k[0] for k in _keys(m)} == {"R_AB_E3"}
    assert m[("R_AB_E3", 0)] == {"345", "312"}
    assert m[("R_AB_E3", 1)] == {"312", "313", "982"}   # 982 Rudolf Otto: a rarer E3 trip
    assert not any("suspendate" in u for u in d.unread)


# --- multi-line event notices --------------------------------------------------------------------


@pytest.mark.parametrize("pid", [10851, 11033, 10878])
def test_event_notices_give_stops_and_a_geometry(pid):
    d = _parse(pid)
    m = _matched(d)
    assert m["geometry"] is not None
    assert ("R_TB_16", 0) in m and ("R_TB_16", 1) in m
    assert ("R_AB_E3", 0) in m and ("R_AB_E3", 1) in m
    # „deviat pe traseul liniei 15” is line 15's route, not a line of the notice
    assert "R_TB_15" not in (d.closure.routeIds or [])
    # where 32, 33 and 33B turn back is named, the stops they lose are not: the person reads it
    assert any("vor întoarce" in u for u in d.unread)


def test_10851_named_stops_per_direction():
    m = _matched(_parse(10851))
    assert m[("R_TB_16", 0)] == {"190", "191", "192"}
    assert m[("R_TB_16", 1)] == {"180", "181", "182"}
    assert m[("R_AB_E3", 0)] == {"331", "131", "129", "985"}
    assert m[("R_AB_E3", 1)] == {"959", "128", "130", "325", "326"}


def test_11033_tur_and_retur_land_on_opposite_directions():
    """„Tur: …” then „Retur: …” for E8 and 21: the second list is the other direction, not merged into one."""
    m = _matched(_parse(11033))
    for rid in ("R_AB_E8", "R_AB_21", "R_AB_5C", "R_AB_E7"):
        assert (rid, 0) in m and (rid, 1) in m, rid
    assert m[("R_AB_21", 0)] == {"370", "371"}
    assert m[("R_AB_21", 1)] == {"398", "399"}


def test_a_list_with_names_not_in_the_gtfs_stays_unread():
    """„Piața Iancu Huniade” (GTFS: „Piața Huniade”) is not matched: the sentence is listed for the person."""
    d = _parse(10851)
    assert any(u.startswith("Vor fi suspendate temporar stațiile: Piața Iancu Huniade") for u in d.unread)


# --- the paste box ---------------------------------------------------------------------------------


def test_pasted_copy_of_a_recorded_notice_is_read_from_its_post_date(state_dir):
    """A notice copied from the web page (title on top, superscript minutes lost) is recognised:
    „Începând de mâine” is the day after 3 Nov, not the day after today."""
    from fastapi.testclient import TestClient

    from app.main import app

    p = _post(11062)
    c = TestClient(app)
    r = c.post("/api/closures/parse", json={"text": p.title + "\n" + p.text.replace(":", "")})
    assert r.status_code == 201
    cl = r.json()["closure"]
    assert cl["window"]["start"] == "2026-11-04T00:00:00+02:00"
    assert cl["sourceUrl"] == p.link
    a = c.post(f"/api/closures/{cl['id']}/analyze").json()
    assert {(s["routeId"], s["stopId"]) for s in a["stops"]} == {("R_AB_E3", "344"), ("R_AB_E3", "314")}


def test_free_text_is_not_taken_for_a_recorded_notice():
    from app.m1_disruption.api_notices import recorded_post

    assert recorded_post("Strada Ardealului închisă între Rahovei și Gogu Opre de mâine, linia E3 deviată.") is None
