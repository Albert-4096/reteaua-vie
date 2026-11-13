"""M2 routing on the real data: a trip around the hero case's suspended stops (SPEC §6.2)."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.config import TZ
from tests.conftest import DATA_DIR, needs_data

pytestmark = needs_data

HERO = "cl_20261108_16dec"
HAS_OSM = (DATA_DIR / "osm" / "timisoara.osm.pbf").is_file()


def _hero_or_skip():
    from app.common import state

    if not state.exists("closures", HERO, state.PART_ANALYSIS):
        pytest.skip("hero case not prepared (make precompute)")


def test_active_closures_follow_the_window():
    from app.m2_routing import plan

    _hero_or_skip()
    during = {c["id"] for c, _ in plan.active_closures(datetime(2026, 11, 8, 12, 0, tzinfo=TZ))}
    after = {c["id"] for c, _ in plan.active_closures(datetime(2026, 11, 8, 19, 0, tzinfo=TZ))}
    assert HERO in during and HERO not in after


def test_avoided_stops_are_the_suspended_pairs_the_baseline_used():
    from app.m2_routing.plan import Option, avoided_stops

    t = datetime(2026, 11, 8, 12, 0, tzinfo=TZ)
    leg = {"mode": "tram", "routeId": "R_TV_4", "fromStopId": "907", "toStopId": "901", "departAt": t, "arriveAt": t,
           "geometry": None}
    other = dict(leg, routeId="R_TV_9", fromStopId="901", toStopId="85")
    lost = frozenset({("907", "R_TV_4", 0), ("901", "R_TV_4", 0), ("85", "R_TV_4", 1)})
    assert avoided_stops(Option([leg, other], t, t), lost) == ["907", "901"]   # 85 is fine on line 9
    assert avoided_stops(None, lost) == []


@pytest.mark.skipif(not HAS_OSM, reason="no OSM extract")
def test_demo_pair_is_a_suspended_line_4_stop_to_piata_victoriei():
    from app.m2_routing import plan
    from app.m4_access import patched_gtfs

    _hero_or_skip()
    frm, to, at, stop = plan.demo_pair()
    _, lost = patched_gtfs.lost_rows(HERO)
    assert any(s == stop and r == "R_TV_4" for s, r, _ in lost)
    assert 21.224 < to[0] < 21.227 and 45.751 < to[1] < 45.755          # the square in OSM
    assert at == datetime(2026, 11, 8, 12, 0, tzinfo=TZ)


@pytest.mark.skipif(not HAS_OSM, reason="no OSM extract")
def test_demo_route_avoids_the_suspended_stops():
    from app.common import jobs
    from app.m2_routing import plan
    from app.m4_access import patched_gtfs, r5
    from app.models.v2 import RoutePlan

    _hero_or_skip()
    if not r5.available():
        pytest.skip("Java / r5py missing")
    frm, to, at, _ = plan.demo_pair()
    p = jobs.compute_and_cache(plan.route_key(frm, to, at), lambda: plan.plan_route(frm, to, at))
    p = RoutePlan.model_validate(p.model_dump(mode="json", by_alias=True))
    _, lost = patched_gtfs.lost_rows(HERO)
    pairs = {(s, r) for s, r, _ in lost}
    rides = [lg for lg in p.legs if lg.routeId]
    assert rides, "the demo trip should use transit"
    for lg in rides:
        assert (lg.fromStopId, lg.routeId) not in pairs and (lg.toStopId, lg.routeId) not in pairs
        assert lg.mode in ("tram", "bus", "trolleybus")
    assert p.avoidedStopIds and all(any(s == a for s, _, _ in lost) for a in p.avoidedStopIds)
    times = [(lg.departAt, lg.arriveAt) for lg in p.legs]
    assert all(datetime.fromisoformat(a) <= datetime.fromisoformat(b) for a, b in times)
    assert 0 < p.durationMinutes < 120
    assert any("R5" in pr.source for pr in p.provenance)


def test_route_endpoint_errors(client):
    to = "21.225307,45.752881"
    assert client.get(f"/api/route?from=1,2&to={to}").json()["error"]["code"] == "OUT_OF_AREA"
    assert client.get(f"/api/route?from=abc&to={to}").status_code == 422
    assert client.get("/api/route?to=21.2,45.75").status_code == 422
    assert client.get(f"/api/route?from=21.21,45.76&to={to}&at=yesterday").status_code == 422
