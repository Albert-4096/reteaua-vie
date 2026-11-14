"""M4 access on the real data: patched GTFS, OSM destinations, GHSL layer, R5 access."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from app.config import TZ
from tests.conftest import DATA_DIR, needs_data

pytestmark = needs_data

HERO = "cl_20261108_16dec"
E3 = "cl_20261107_e3"
HAS_OSM = (DATA_DIR / "osm" / "timisoara.osm.pbf").is_file()
HAS_POP = (DATA_DIR / "pop" / "ghsl_2020_100m.tif").is_file()


def _hero_or_skip():
    from app.common import state
    from app.m4_access import patched_gtfs as pg

    if not state.exists("closures", HERO, state.PART_ANALYSIS):
        pytest.skip("hero case not prepared (make precompute)")
    return pg.lost_rows(HERO)


def _calls(path, start, end) -> dict:
    """All scheduled calls (arrivals included) per (stop, route, dir) in [start, end)."""
    from app.common.timeutil import gtfs_service_start
    from app.m4_access import patched_gtfs as pg

    t = pg._read_tables(path)
    days = pg.service_dates(t["calendar"], t["calendar_dates"])
    tr = t["trips"].set_index("trip_id")
    st = t["stop_times"]
    sec = pg._hms(st["departure_time"])
    route = tr.loc[st["trip_id"], "route_id"].to_numpy()
    direction = tr.loc[st["trip_id"], "direction_id"].to_numpy().astype(int)
    sid = tr.loc[st["trip_id"], "service_id"].to_numpy()
    out: dict = {}
    d = (start - timedelta(days=1)).date()
    while d <= end.date():
        active = {k for k, v in days.items() if d in v}
        base = int(gtfs_service_start(d).timestamp())
        ts = base + sec
        m = np.isin(sid, list(active)) & (ts >= start.timestamp()) & (ts < end.timestamp())
        for k in zip(st["stop_id"].to_numpy()[m], route[m], direction[m]):
            out[k] = out.get(k, 0) + 1
        d += timedelta(days=1)
    return out


def test_patched_gtfs_removes_exactly_the_lost_calls_inside_the_window():
    from app.common.timeutil import parse_iso
    from app.m4_access import patched_gtfs as pg

    closure, lost = _hero_or_skip()
    pf = pg.patched_for(closure, lost)
    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    before, after = _calls(pf.base_path, start, end), _calls(pf.path, start, end)
    assert sum(before.get(k, 0) for k in lost) > 0
    assert sum(after.get(k, 0) for k in lost) == 0, "a suspended call is still in the patched feed"
    others = set(before) | set(after)
    assert all(before.get(k, 0) == after.get(k, 0) for k in others if k not in lost)
    # the day before the works is untouched, except the one call before 10:00 of a trip whose every
    # later call is suspended (a trip with one call left is dropped: it carries nobody)
    b0, a0 = _calls(pf.base_path, start - timedelta(days=1), start), _calls(pf.path, start - timedelta(days=1), start)
    assert all(b0.get(k, 0) == a0.get(k, 0) for k in set(b0) | set(a0) if k not in lost)
    assert sum(b0.get(k, 0) - a0.get(k, 0) for k in lost) <= pf.trips_cancelled


def test_patched_gtfs_departures_lost_match_the_impact():
    """Departures (not last calls) at the lost rows = the Impact's departuresLost, and none remain."""
    from app.common.timeutil import parse_iso
    from app.m1_disruption import impact as imp
    from app.m4_access import patched_gtfs as pg

    closure, lost = _hero_or_skip()
    pf = pg.patched_for(closure, lost)
    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    base = imp.HistoryTimetable(pf.base_path).counts(start, end)
    patched = imp.HistoryTimetable(pf.path).counts(start, end)
    expected = imp.compute_impact(HERO).totals.departuresLost
    assert sum(base.get(k, 0) for k in lost) == expected
    assert sum(patched.get(k, 0) for k in lost) == 0


def test_patch_is_cached_by_decisions():
    from app.m4_access import patched_gtfs as pg

    closure, lost = _hero_or_skip()
    a = pg.patched_for(closure, lost)
    assert pg.patched_for(closure, lost).path == a.path
    fewer = set(sorted(lost)[1:])
    assert pg.patched_for(closure, fewer).path != a.path


@pytest.mark.skipif(not HAS_OSM, reason="no OSM extract")
def test_destinations_layer_from_osm():
    from app.m4_access import layers
    from app.models.v2 import LayerCollection

    lc = LayerCollection.model_validate(layers.destinations_layer())
    kinds = {f.properties["kind"] for f in lc.features}
    assert kinds >= {"hospital", "school", "rail_station"} and kinds <= {"hospital", "school", "rail_station", "landmark"}
    hospitals = [f.properties for f in lc.features if f.properties["kind"] == "hospital"]
    assert hospitals and all(not h["osmId"].startswith("node/") for h in hospitals)  # polygons only
    stations = {f.properties["name"] for f in lc.features if f.properties["kind"] == "rail_station"}
    assert "Timișoara Nord" in stations
    assert lc.provenance and "OpenStreetMap" in lc.provenance[0].source
    small = layers.destinations_layer((21.20, 45.74, 21.23, 45.76))
    assert 0 < len(small["features"]) < len(lc.features)


@pytest.mark.skipif(not HAS_POP, reason="no GHSL raster")
def test_population_layer_is_ghsl_cells_with_label():
    from app.m4_access import layers
    from app.models.v2 import LayerCollection

    bbox = (21.20, 45.74, 21.24, 45.77)
    lc = LayerCollection.model_validate(layers.population_layer(bbox))
    assert len(lc.features) > 100
    assert all(f.geometry.type == "Polygon" for f in lc.features[:20])
    assert all(f.properties["residents"] > 0 for f in lc.features)
    assert "nu recensământ" in (lc.provenance[0].note or "")


def test_access_time_is_window_start_inside_service_else_weekday_morning():
    from app.m1_disruption import impact as imp
    from app.m4_access.access import choose_at

    tt = imp.current_timetable()
    sun = datetime(2026, 11, 8, 10, 0, tzinfo=TZ)
    assert choose_at(sun, sun + timedelta(hours=8), tt) == sun
    night = datetime(2026, 11, 7, 1, 0, tzinfo=TZ)                    # Saturday 01:00, no service
    at = choose_at(night, night + timedelta(days=5), tt)
    assert at == datetime(2026, 11, 9, 8, 0, tzinfo=TZ)                # next weekday 08:00
    e3 = datetime(2026, 11, 7, 4, 0, tzinfo=TZ)                        # E3: Saturday 04:00, early trips only
    assert choose_at(e3, datetime(2026, 11, 13, 0, 0, tzinfo=TZ), tt) == datetime(2026, 11, 9, 8, 0, tzinfo=TZ)


@pytest.mark.skipif(not (HAS_OSM and HAS_POP), reason="no OSM / GHSL")
def test_r5_travel_times_never_improve_on_the_patched_feed():
    """Four origins near line 4 stops, to the hospitals: with the closure, no time gets shorter."""
    from app.common.timeutil import parse_iso
    from app.m4_access import access, patched_gtfs as pg, r5

    if not r5.available():
        pytest.skip("Java / r5py missing")
    closure, lost = _hero_or_skip()
    pf = pg.patched_for(closure, lost)
    at = parse_iso(closure["window"]["start"])
    o = r5.points_frame(["a", "b", "c", "d"], [21.2140, 21.2208, 21.2310, 21.2016],
                        [45.7581, 45.7525, 45.7505, 45.7613])
    d = access._dest_frame("hospital")
    b = r5.travel_times(pf.base_path, o, d, at, 45).set_index(["from_id", "to_id"])["travel_time"]
    a = r5.travel_times(pf.path, o, d, at, 45).set_index(["from_id", "to_id"])["travel_time"]
    assert b.notna().sum() > 0
    joined = b.to_frame("b").join(a.to_frame("a"))
    both = joined.dropna()
    assert (both["a"] >= both["b"] - 1).all()      # 1 min slack: median over the departure window
    assert joined["a"].notna().sum() <= joined["b"].notna().sum()


def test_access_cached_result_is_consistent():
    """The warmed AccessImpact (make precompute) is a valid estimate with consistent totals."""
    from app.common import jobs
    from app.m4_access.api_access import access_key
    from app.models.v2 import AccessImpact

    _hero_or_skip()
    hit = jobs.cached(access_key(HERO, "hospital", 30))
    if hit is None:
        pytest.skip("access not warmed yet (make precompute)")
    a = AccessImpact.model_validate(hit.model_dump(mode="json", by_alias=True))
    assert a.estimate is True and a.dest == "hospital" and a.minutes == 30
    assert len(a.byZone) == 40
    t = a.totals
    assert t.residentsBefore == sum(z.residentsBefore for z in a.byZone)
    assert t.residentsLosing == sum(z.residentsLosing for z in a.byZone)
    assert 0 <= t.residentsLosing <= t.residentsBefore
    assert all(z.residentsBefore - z.residentsLosing <= z.residentsAfter for z in a.byZone)
    assert any("GHSL" in p.source for p in a.provenance)


def test_access_endpoint_errors(client):
    r = client.get("/api/closures/does_not_exist/access")
    assert r.status_code == 404
    r = client.get(f"/api/closures/{HERO}/access?minutes=5")
    assert r.status_code == 422
    r = client.get(f"/api/closures/{HERO}/access?dest=pharmacy")
    assert r.status_code == 422


def test_frequency_mitigation_adds_trips_but_never_a_suspended_call():
    """SPEC §6.4 `frequency`: line 7 every 6 min in the hero window; line 4 is suspended, so nothing is added."""
    from app.common.timeutil import parse_iso
    from app.m1_disruption import impact as imp
    from app.m4_access import patched_gtfs as pg

    closure, lost = _hero_or_skip()
    freq = [{"routeId": "R_TV_7", "headwayMinutes": 6}, {"routeId": "R_TV_4", "headwayMinutes": 6}]
    pf = pg.patched_for(closure, lost, freq)
    plain = pg.patched_for(closure, lost)
    assert pf.path != plain.path and pf.trips_added > 0
    assert any(n.startswith("R_TV_4: nicio cursă") for n in pf.frequency_notes)
    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    with_f, without = imp.HistoryTimetable(pf.path).counts(start, end), imp.HistoryTimetable(plain.path).counts(start, end)
    assert sum(n for k, n in with_f.items() if k[1] == "R_TV_7") > sum(n for k, n in without.items() if k[1] == "R_TV_7")
    assert sum(with_f.get(k, 0) for k in lost) == 0
    assert all(with_f.get(k, 0) == without.get(k, 0) for k in set(with_f) | set(without) if k[1] != "R_TV_7")


def test_d012_decisions_for_the_pre_warm_match_the_eval_rule():
    """The hero with the 11067 gold label as clerk decisions: 21 rows ticked, 29 ring rows unticked (D-012)."""
    from app.common import state
    from app.m4_access import warm

    _hero_or_skip()
    stored = state.read("closures", HERO, state.PART_ANALYSIS)
    a = warm.gold_analysis()
    if a is None:
        pytest.skip("no gold label")
    assert sum(1 for r in a["stops"] if r.get("confirmed") is True) == 21
    assert sum(1 for r in a["stops"] if r.get("confirmed") is False) == 29
    assert state.read("closures", HERO, state.PART_ANALYSIS) == stored   # nothing written


def test_access_key_depends_on_the_lost_rows_not_on_who_decided():
    from app.m4_access import access, warm

    closure, lost = _hero_or_skip()
    k = access.access_key(closure, lost, "hospital", 30)
    assert k == access.access_key(closure, set(sorted(lost)), "hospital", 30)
    assert k != access.access_key(closure, lost, "school", 30)
    a = warm.gold_analysis()
    if a is not None:
        from app.m1_disruption import impact as imp

        decided = {imp.row_key(r) for r in a["stops"] if imp.counts_as_lost(r)}
        assert decided != lost and access.access_key(closure, decided, "hospital", 30) != k
