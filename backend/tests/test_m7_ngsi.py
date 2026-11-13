"""T7-C: GET /api/feed/alerts.ngsi.json, the published alerts as NGSI-LD (FIWARE Alert + GtfsStop)."""

from __future__ import annotations

from app.common import state
from app.common.timeutil import parse_iso
from app.m7_compliance import ngsi
from tests.conftest import needs_data

CID = "cl_test_ngsi"
STOP = "356"   # Piața A. Mocioni: a real stop of the city network
# dataModel.Alert: the required attributes and the subCategory values we use (schema.json)
REQUIRED = {"id", "type", "alertSource", "category", "dateIssued"}
WINDOW = {"start": "2026-11-08T10:00:00+02:00", "end": "2026-11-08T18:00:00+02:00"}
GEOMETRY = {"type": "LineString", "coordinates": [[21.2149, 45.7452], [21.2156, 45.7457]]}


def _alert(aid: str, stop_id: str | None) -> dict:
    return {"id": aid, "closureId": CID, "activePeriod": [WINDOW], "cause": "CONSTRUCTION", "effect": "DETOUR",
            "informedEntity": [{"routeId": "R_AB_M32", "stopId": stop_id, "directionId": 0 if stop_id else None}],
            "headerText": {"ro": "Antet", "en": "Header"}, "descriptionText": {"ro": "Descriere", "en": "Text"},
            "url": f"https://example.invalid/a/{CID}" + (f"?stop={stop_id}" if stop_id else "")}


def _store():
    state.write("closures", CID, {"id": CID, "status": "published", "window": WINDOW, "geometry": GEOMETRY,
                                  "sourceUrl": "https://stpt.ro/x/"})
    state.write("published", CID, {"closureId": CID, "alerts": [_alert("al_r", None), _alert("al_s", STOP)],
                                   "feedUrl": "x", "posters": [], "publishedAt": "2026-11-06T09:30:00+02:00"})


def _check_entities(items: list[dict]) -> None:
    ids = {e["id"] for e in items}
    for e in items:
        assert e["id"].startswith(f"urn:ngsi-ld:{e['type']}:") and e["@context"]
        loc = e.get("location")
        if loc and loc["value"]["type"] == "Point":
            lon, lat = loc["value"]["coordinates"]
            assert 20.5 < lon < 22 and 45 < lat < 46.5, "GeoJSON order is [lng, lat]"
        if e["type"] == "Alert":
            assert REQUIRED <= set(e)
            assert e["category"]["value"] == "traffic"
            assert e["subCategory"]["value"] in ("roadWorks", "roadClosed")
            for k in ("dateIssued", "validFrom", "validTo"):
                assert e[k]["value"]["@type"] == "DateTime" and e[k]["value"]["@value"].endswith("Z")
            if "refGtfsStop" in e:
                assert e["refGtfsStop"]["type"] == "Relationship" and e["refGtfsStop"]["object"] in ids
        else:
            assert e["type"] == "GtfsStop" and {"name", "location"} <= set(e)


@needs_data
def test_entities_of_a_published_closure(isolated_state):
    _store()
    items = ngsi.entities(parse_iso("2026-11-08T12:00:00+02:00"))
    _check_entities(items)
    by_id = {e["id"]: e for e in items}
    route, stop = by_id[ngsi.alert_urn("al_r")], by_id[ngsi.alert_urn("al_s")]
    assert route["location"]["value"] == GEOMETRY and "refGtfsStop" not in route   # the closed section
    assert stop["refGtfsStop"]["object"] == ngsi.stop_urn(STOP)
    assert stop["alertSource"]["value"] == "https://stpt.ro/x/"
    assert stop["dateIssued"]["value"]["@value"] == "2026-11-06T07:30:00Z"          # publish time, UTC
    assert stop["validFrom"]["value"]["@value"] == "2026-11-08T08:00:00Z"
    assert stop["data"]["value"]["gtfsRtEffect"] == "DETOUR"
    gtfs_stop = by_id[ngsi.stop_urn(STOP)]
    assert gtfs_stop["name"]["value"].startswith("Piața A. Mocioni") and gtfs_stop["code"]["value"] == STOP
    assert [e["type"] for e in items].count("GtfsStop") == 1
    assert ngsi.entities(parse_iso("2026-11-08T18:00:00+02:00")) == []                 # ended: not exported


@needs_data
def test_endpoint_and_export_list(client):
    r = client.get("/api/feed/alerts.ngsi.json")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/ld+json")
    _check_entities(r.json())
    names = {f["name"]: f for f in client.get("/api/exports").json()}
    assert names["alerts.ngsi.json"]["format"] == "NGSI-LD"
    assert names["alerts.ngsi.json"]["url"].endswith("/api/feed/alerts.ngsi.json")
