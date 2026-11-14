"""R2: GET /api/lines/status (app/lines/status.py).

The hero closure (8 Nov, Bd. 16 Decembrie 1989) is stored as analyzed and published live in
the demo; here a copy is published in a temp state dir, with the E3 closure (7-13 Nov).
"""

from __future__ import annotations

import json

import pytest

from app.common import state
from tests.conftest import DATA_DIR, needs_data

CLOSURES = DATA_DIR / "state" / "closures"
needs_cases = pytest.mark.skipif(not (CLOSURES / "cl_20261108_16dec.json").is_file(), reason="no stored cases")

AT = "2026-11-08T12:00:00+02:00"


@pytest.fixture
def published(isolated_state):
    for cid in ("cl_20261108_16dec", "cl_20261107_e3"):
        c = json.loads((CLOSURES / f"{cid}.json").read_text(encoding="utf-8"))
        state.write("closures", cid, {**c, "status": "published"})
    return isolated_state


def _by_route(body: dict) -> dict:
    return {(x["routeId"] or x["shortName"]): x for x in body["lines"]}


@needs_data
@needs_cases
def test_demo_clock_hero_lines(client, published):
    r = client.get("/api/lines/status", params={"at": AT})
    assert r.status_code == 200
    lines = _by_route(r.json())
    l4 = lines["R_TV_4"]
    assert (l4["state"], l4["replacedBy"], l4["directionIds"]) == ("suspendata", ["4b"], None)
    assert l4["until"] == "2026-11-08T18:00:00+02:00" and l4["closureId"] == "cl_20261108_16dec"
    assert l4["notice"]["postId"] == 11067 and l4["label"]["ro"] == "suspendată"
    assert lines["R_TV_2"]["state"] == "scurtata" and lines["R_TV_7"]["state"] == "scurtata"
    assert lines["R_TV_2"]["replacedBy"] == []
    assert lines["4b"]["state"] == "linie_temporara" and lines["4b"]["mode"] == "autobuz"
    assert lines["R_AB_E3"]["state"] == "deviata" and lines["R_AB_E3"]["notice"]["postId"] == 11065
    assert lines["R_TV_1"]["state"] == "normala" and lines["R_TV_1"]["since"] is None
    assert not [x for x in lines.values() if x["state"] == "fara_vehicul"]  # only after a person confirms (R4)
    assert any(p["version"] == "11067" for p in r.json()["provenance"])


@needs_data
@needs_cases
def test_changes_since_and_route_filter(client, published):
    body = client.get("/api/lines/status", params={"at": AT, "since": "2026-11-08T09:00:00+02:00"}).json()
    changed = _by_route(body)
    assert set(changed) == {"R_TV_4", "R_TV_2", "R_TV_7", "4b"}  # E3 was already diverted at 09:00
    assert changed["R_TV_4"]["previousState"] == "normala" and changed["4b"]["previousState"] is None

    one = client.get("/api/lines/status", params={"at": AT, "routeId": "R_TV_4"}).json()
    assert [x["routeId"] or x["shortName"] for x in one["lines"]] == ["R_TV_4", "4b"]

    after = _by_route(client.get("/api/lines/status", params={"at": "2026-11-08T19:00:00+02:00"}).json())
    assert after["R_TV_4"]["state"] == "normala" and "4b" not in after


@needs_data
def test_rejects_since_after_at(client):
    r = client.get("/api/lines/status", params={"at": AT, "since": "2026-11-08T13:00:00+02:00"})
    assert r.status_code == 422
