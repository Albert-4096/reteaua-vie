"""R1-B: street search over the City Hall register and the section between two map clicks."""

from __future__ import annotations

import pytest

from conftest import needs_data

pytestmark = needs_data

ARDEALULUI = "11068"   # register id; codGis 38
AT_RAHOVEI = "21.19245,45.73895"      # clicks near the two junctions of notice 11065
AT_GOGU_OPRE = "21.18795,45.73608"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


@pytest.mark.parametrize("q", ["ardealului", "Strada Ardealului", "str. ardeal", "ARDEALULUI"])
def test_search_ignores_case_diacritics_and_the_type_word(client, q):
    body = client.get("/api/streets", params={"q": q}).json()
    top = body["streets"][0]
    assert (top["name"], top["codGis"], top["streetId"], top["hasGeometry"]) == ("Strada Ardealului", "38", ARDEALULUI, True)
    assert body["query"] == q
    assert [p["source"] for p in body["provenance"]][0].startswith("Primăria Timișoara, nomenclatorul stradal")


def test_search_ranks_whole_words_first_and_reads_numbers(client):
    names = [s["name"] for s in client.get("/api/streets", params={"q": "mihai"}).json()["streets"]]
    assert names.index("Bulevardul Mihai Viteazu") < names.index("Strada Mihail Jora")
    top = client.get("/api/streets", params={"q": "bd 16 dec"}).json()["streets"][0]
    assert top["name"] == "Bulevardul 16 Decembrie 1989"
    assert client.get("/api/streets", params={"q": "polona"}).json()["streets"][0]["name"] == "Strada Polonă"


def test_search_needs_two_letters(client):
    r = client.get("/api/streets", params={"q": "x"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_INPUT"


def test_section_between_two_clicks(client):
    r = client.get(f"/api/streets/{ARDEALULUI}/section", params={"from": AT_RAHOVEI, "to": AT_GOGU_OPRE})
    assert r.status_code == 200
    s = r.json()
    assert (s["name"], s["codGis"], s["whole"]) == ("Strada Ardealului", "38", False)
    assert s["geometry"]["type"] == "LineString"
    assert 400 < s["lengthMeters"] < 550          # Rahovei -> Martir Gogu Opre, measured on the OSM ways
    first = s["geometry"]["coordinates"][0]
    assert abs(first[0] - 21.1924) < 0.001 and abs(first[1] - 45.7389) < 0.001   # starts at the first click
    whole = client.get(f"/api/streets/{ARDEALULUI}/section").json()
    assert whole["whole"] and whole["lengthMeters"] > s["lengthMeters"]


def test_section_errors(client):
    far = client.get(f"/api/streets/{ARDEALULUI}/section", params={"from": "21.2087,45.7489", "to": AT_GOGU_OPRE})
    assert far.status_code == 422 and far.json()["error"]["code"] == "NOT_ON_STREET"
    one = client.get(f"/api/streets/{ARDEALULUI}/section", params={"from": AT_RAHOVEI})
    assert one.status_code == 422
    bad = client.get(f"/api/streets/{ARDEALULUI}/section", params={"from": "45.7389,21.1924", "to": AT_GOGU_OPRE})
    assert bad.status_code == 422
    assert client.get("/api/streets/999/section").json()["error"]["code"] == "NO_SUCH_STREET"


def test_section_feeds_a_drawn_closure():
    """The section is a valid ClosureInput geometry, and the drawn closure finds E3 on Ardealului."""
    from app.m1_disruption import matching, streets
    from app.models.v1 import ClosureInput

    s = streets.section(ARDEALULUI, streets.parse_point(AT_RAHOVEI, "from"), streets.parse_point(AT_GOGU_OPRE, "to"))
    ci = ClosureInput.model_validate({
        "title": {"ro": "Str. Ardealului", "en": "Ardealului St"}, "kind": "drawn",
        "geometry": s.geometry.model_dump(), "bufferMeters": 30, "direction": "both",
        "window": {"start": "2026-11-07T04:00:00+02:00", "end": "2026-11-13T00:00:00+02:00"},
        "routeIds": None, "sourceText": None, "sourceUrl": None, "routeActions": None, "temporaryRoutes": None})
    rows = matching.match_drawn(ci.model_dump(mode="json", by_alias=True))
    assert rows and {r["routeId"] for r in rows} == {"R_AB_E3"}
