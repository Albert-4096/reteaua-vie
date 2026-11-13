"""T11: the hero closure is drawn where the notice's lines meet, not on track other lines keep using."""

from __future__ import annotations

from shapely.geometry import shape

from tests.conftest import needs_data

pytestmark = needs_data


def test_hero_geometry_is_the_piata_maria_junction():
    from app.cases import build
    from app.cases.catalog import CASES_BY_CLOSURE
    from app.common.city import load_network, route_mode
    from app.common.geo import to_metric
    from app.m1_disruption import matching as m
    from app.m1_disruption import parser

    case = CASES_BY_CLOSURE["cl_20261108_16dec"]
    b = build.build_case(case)   # not saved: the real state is only read
    c = b.closure
    g = to_metric(shape(c.geometry.model_dump()))
    assert 10 <= g.length <= 15.5                   # the notice: „aproximativ 10 m – 15 m”
    assert c.direction == "along" and c.locationNote is not None and b.approximate
    bd = to_metric(parser.street_geometry(parser.resolve_street("Bulevardul 16 Decembrie 1989")))
    assert bd.distance(g) <= 15                     # on Bd. 16 Decembrie 1989
    trams = {r for r, _ in load_network().path_lines if route_mode(r) == "tram"}
    near = {r for r in trams for d in (0, 1)
            if m.path_metric(r, d) is not None and m.path_metric(r, d).distance(g) <= c.bufferMeters}
    assert near == set(case.route_ids) == {"R_TV_2", "R_TV_4", "R_TV_7"}   # lines 1 and 8 keep running
    # the rows still come from the notice's route actions, not from the drawing
    rows, _ = m.match_closure(c.model_dump(mode="json"))
    assert {r["routeId"] for r in rows} == set(case.route_ids)
