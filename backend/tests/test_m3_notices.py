"""M3 neighbourhood notices on the real prepared cases (SPEC §6.3)."""

from __future__ import annotations

import json
import threading
from datetime import datetime

import pytest

from app import config
from app.common import state
from app.config import TZ
from tests.conftest import DATA_DIR, needs_data

HERO = "cl_20261108_16dec"
E3 = "cl_20261107_e3"
MOCIONI = "cl_20261102_mocioni"


def _stored(closure_id: str) -> tuple[dict, dict]:
    c = state.read("closures", closure_id)
    a = state.read("closures", closure_id, state.PART_ANALYSIS)
    if c is None or a is None:
        pytest.skip(f"{closure_id} not prepared (run make precompute)")
    return c, a


def _register() -> set[tuple[str, str]]:
    raw = json.loads((DATA_DIR / "city-api-2026-11-13" / "nomenclator-strazi.json").read_text(encoding="utf-8"))
    return {(r["denumireCompleta"], str(r["codGis"])) for r in raw["strazi"] if r.get("codGis")}


def _lost_stops(analysis: dict) -> set[str]:
    from app.m1_disruption.impact import counts_as_lost

    return {str(r["stopId"]) for r in analysis["stops"] if counts_as_lost(r)}


def test_window_phrase():
    from app.m3_notices.notices import window_phrase

    s = datetime(2026, 11, 8, 10, tzinfo=TZ)
    e = datetime(2026, 11, 8, 18, tzinfo=TZ)
    assert window_phrase(s, e, "ro") == "duminică 8 noiembrie 2026, 10:00–18:00"
    assert window_phrase(s, e, "en") == "Sunday 8 November 2026, 10:00–18:00"
    e3s, e3e = datetime(2026, 11, 7, 4, tzinfo=TZ), datetime(2026, 11, 13, 0, tzinfo=TZ)
    assert window_phrase(e3s, e3e, "ro") == "sâmbătă 7 noiembrie 2026, 04:00 – joi 12 noiembrie 2026, 24:00"
    assert window_phrase(s, e, "ro", open_end=True).endswith("până la finalizarea lucrărilor")


@needs_data
@pytest.mark.parametrize("closure_id", [HERO, E3, MOCIONI])
def test_one_notice_per_zone_hit(closure_id):
    from app.common.city import load_zones, zone_for_point
    from app.m1_disruption.impact import counts_as_lost
    from app.m3_notices import notices
    from app.m6_parking.parking import closure_buffer

    closure, analysis = _stored(closure_id)
    out = notices.notices_for(closure_id)
    zones = load_zones()
    by_stop = {r["zoneSlug"] or zone_for_point(*r["location"]) for r in analysis["stops"] if counts_as_lost(r)}
    by_buffer = {zones.slugs[int(i)] for i in zones.tree.query(closure_buffer(closure), predicate="intersects")}
    expected = (by_stop | by_buffer) & set(zones.names)
    slugs = [n.zoneSlug for n in out]
    assert len(slugs) == len(set(slugs)) and set(slugs) == expected
    lost = _lost_stops(analysis)
    for n in out:
        assert n.closureId == closure_id and n.zoneName == zones.names[n.zoneSlug]
        assert set(n.stopIds) <= lost
        assert n.window.start == closure["window"]["start"] and n.window.end == closure["window"]["end"]
        assert n.body.ro and n.body.en and n.title.ro.startswith(n.zoneName)
        assert "vor fi încetinite" not in n.body.ro
        if closure.get("status") != "published":
            assert n.publishedAt is None and n.alertIds == []


@needs_data
def test_codgis_comes_from_the_register_or_is_null():
    from app.m3_notices import notices

    reg = _register()
    names = {name for name, _ in reg}
    seen = 0
    for cid in (HERO, E3, MOCIONI):
        _stored(cid)
        for n in notices.notices_for(cid):
            for s in n.streets:
                seen += 1
                if s.codGis is None:
                    assert s.name not in names
                else:
                    assert (s.name, s.codGis) in reg
    assert seen


@needs_data
def test_e3_text_uses_the_real_names_and_distances():
    from app.m1_disruption.alerts import pick_nearest
    from app.m3_notices import notices

    _closure, analysis = _stored(E3)
    out = {n.zoneSlug: n for n in notices.notices_for(E3)}
    ard = [n for n in out.values() if any(s.name == "Strada Ardealului" for s in n.streets)]
    assert ard, "Strada Ardealului is inside the E3 buffer"
    assert ard[0].streets[0].codGis is not None
    for n in out.values():
        assert n.routeIds == ["R_AB_E3"]
        assert "Linia E3" in n.body.ro and "Line E3" in n.body.en
        assert n.body.ro.startswith("Sâmbătă 7 noiembrie 2026, 04:00 – joi 12 noiembrie 2026, 24:00: lucrări pe")
        for stop_id in n.stopIds:
            rows = [r for r in analysis["stops"] if str(r["stopId"]) == stop_id]
            near = pick_nearest(rows, stop_id)
            if near and near.get("distanceMeters") is not None and str(near["stopId"]) != stop_id:
                assert near["name"] in n.body.ro


@needs_data
def test_hero_zone_hit_only_by_a_stop_has_no_streets():
    from app.m3_notices import notices
    from app.m6_parking.parking import closure_buffer
    from app.common.city import load_zones

    closure, _analysis = _stored(HERO)
    zones = load_zones()
    buf = closure_buffer(closure)
    far = [n for n in notices.notices_for(HERO)
           if not zones.shapes[zones.slugs.index(n.zoneSlug)].intersects(buf)]
    assert far, "line 4 is suspended on its whole route, far from the works"
    for n in far:
        assert n.streets == [] and n.stopIds
        assert "Linia 4 nu circulă." in n.body.ro and "Line 4 does not run." in n.body.en
        assert "Bulevardul 16 Decembrie 1989" in n.body.ro            # where the works are


@pytest.fixture
def published_state(tmp_path, monkeypatch):
    """A temp state dir holding a copy of the prepared E3 closure; the other data are linked in."""
    real = config.get_settings()
    closure = state.read("closures", E3)
    analysis = state.read("closures", E3, state.PART_ANALYSIS)
    if closure is None or analysis is None:
        pytest.skip("E3 not prepared (run make precompute)")
    for entry in real.data_dir.iterdir():
        if entry.name not in ("state",):
            (tmp_path / entry.name).symlink_to(entry)
    fake = config.Settings(env_file=None, data_dir=tmp_path, live_dir=real.live_dir, demo_now=real.demo_now,
                           data_freeze=False, public_base_url=real.public_base_url)
    monkeypatch.setattr(config, "get_settings", lambda: fake)
    import app.common.state as state_mod

    monkeypatch.setattr(state_mod, "get_settings", lambda: fake)
    config.ensure_dirs(fake)
    state.write("closures", E3, closure)
    state.write("closures", E3, analysis, state.PART_ANALYSIS)
    yield fake


@needs_data
def test_publish_fills_alert_ids_and_the_feed(published_state):
    from app.m1_disruption import publish
    from app.m3_notices import notices

    before = notices.notices_for(E3)
    assert notices.feed() == []
    result = publish.publish(E3)
    after = notices.notices_for(E3)
    assert [n.id for n in after] == [n.id for n in before]
    alert_ids = {a.id for a in result.alerts}
    for n in after:
        assert n.publishedAt == result.publishedAt
        assert n.alertIds and set(n.alertIds) <= alert_ids
        for aid in n.alertIds:
            alert = next(a for a in result.alerts if a.id == aid)
            assert any(e.stopId in n.stopIds for e in alert.informedEntity)
    # every stop alert lands in some zone's notice
    covered = {a for n in after for a in n.alertIds}
    assert {a.id for a in result.alerts if "_stop_" in a.id} <= covered
    # the feed: active at the demo clock (8 Nov 12:00), gone after the window (13 Nov 00:00)
    assert [n.id for n in notices.feed(datetime(2026, 11, 8, 12, tzinfo=TZ))] == [n.id for n in after]
    assert notices.feed(datetime(2026, 11, 13, 0, tzinfo=TZ)) == []


@needs_data
def test_notice_endpoints(client):
    _stored(E3)
    r = client.get(f"/api/closures/{E3}/notices")
    assert r.status_code == 200, r.text
    from app.m3_notices.notices import ZoneNotice

    notices = [ZoneNotice.model_validate(n) for n in r.json()]
    assert notices and all(n.closureId == E3 for n in notices)
    assert client.get("/api/closures/no_such_closure/notices").status_code == 404
    feed = client.get("/api/feed/notices.json")
    assert feed.status_code == 200 and isinstance(feed.json(), list)
    for n in feed.json():
        assert n["publishedAt"] is not None
    # let the routers' background warm-ups finish: a short run must not exit while they are in C code
    for t in threading.enumerate():
        if t.name.endswith("-warm"):
            t.join(180)


@needs_data
def test_warm_runs_on_the_prepared_cases():
    from app.m3_notices.warm import warm

    warm([HERO, E3, MOCIONI])
