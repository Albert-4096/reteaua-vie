from app.common import state
from app.models.v2 import MitigationTransitThrough
from tests.conftest import needs_data

E3 = "cl_20261107_e3"
MOCIONI = "cl_20261102_mocioni"
HERO = "cl_20261108_16dec"


def _mit(**kw):
    return MitigationTransitThrough(kind="transit_through", **kw)


@needs_data
def test_scenario_mitigation_drops_rows_when_the_lane_is_confirmed():
    from app.m4_access import scenarios

    closure = state.read("closures", E3)
    rows = state.read("closures", E3, "analysis")["stops"]
    c, new_rows, notes = scenarios.apply_mitigations(closure, rows, [_mit(lanesConfirmed=True)])
    assert len(new_rows) < len(rows) and not [r for r in new_rows if r["routeId"] == "R_AB_E3"]
    assert c["routeActions"] is None
    n = notes[-1]
    assert n.kind == "transit_through" and "plecări păstrate" in n.text.ro and "lățimea benzii" in n.text.ro
    assert n.value == sum(r.get("departuresLost") or 0 for r in rows)
    assert closure["routeActions"], "the stored closure is untouched"


@needs_data
def test_cannot_judge_keeps_every_row_and_says_so():
    from app.m4_access import scenarios

    closure = state.read("closures", E3)  # Strada Ardealului: no lanes and no width in OSM
    rows = state.read("closures", E3, "analysis")["stops"]
    _c, new_rows, notes = scenarios.apply_mitigations(closure, rows, [_mit()])
    assert new_rows == rows and "nu se poate judeca din date" in notes[-1].text.ro
    assert "lanes" in notes[-1].text.ro


@needs_data
def test_endpoint_applied_cannot_judge_and_tram(client):
    ok = client.get(f"/api/closures/{MOCIONI}/transit-through").json()
    assert ok["verdict"] == "applied" and ok["kept"]["departures"] == ok["full"]["departuresLost"] > 0
    assert ok["variant"]["departuresLost"] == 0 and "plecări păstrate" in ok["note"]["ro"]
    e3 = client.get(f"/api/closures/{E3}/transit-through").json()
    assert e3["verdict"] == "cannot_judge" and e3["full"] == e3["variant"] and e3["streets"][0]["enough"] is None
    forced = client.get(f"/api/closures/{E3}/transit-through?lanesConfirmed=true").json()
    assert forced["verdict"] == "applied" and forced["kept"]["residentsKeepingStop"] == forced["full"]["residentsLosingStop"]
    hero = client.get(f"/api/closures/{HERO}/transit-through").json()
    assert hero["verdict"] == "cannot_judge" and any("tramvai" in r["ro"] for r in hero["reasons"])
    assert hero["excludedRoutes"] and "tramvai" in hero["excludedRoutes"][0]["reason"]["ro"]
    assert client.get(f"/api/closures/{MOCIONI}/transit-through?routeIds=nope").status_code == 422
    assert client.get("/api/closures/nope/transit-through").status_code == 404


def test_scenario_input_accepts_the_new_kind():
    from app.models.v2 import ScenarioInput

    s = ScenarioInput.model_validate({"closureId": "x", "title": {"ro": "t", "en": "t"},
                                      "mitigations": [{"kind": "transit_through", "routeIds": ["R_AB_E3"]}]})
    assert s.mitigations[0].lanesConfirmed is False
