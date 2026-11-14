from fastapi.testclient import TestClient

from app.common.city import load_landmarks
from app.m4_access import access, layers
from tests.conftest import needs_data


@needs_data
def test_landmarks_loaded_exactly_as_given():
    got = load_landmarks()
    assert got is not None
    items, p = got
    assert len(items) == 20 and "api/mobile/pois, preluat" in p.note
    assert any(x.name == "Catedrala Mitropolitană Ortodoxă" and x.nameEn == "Orthodox Metropolitan Cathedral" for x in items)


@needs_data
def test_landmark_is_a_destination_kind_and_layer_feature():
    assert "landmark" in access.DESTS
    assert len(layers.destinations("landmark")) == 20
    feats = [f for f in layers.destinations_layer()["features"] if f["properties"]["kind"] == "landmark"]
    assert len(feats) == 20 and feats[0]["properties"]["osmId"].startswith("poi/")
    assert "ghidul turistic" in access.method_text("landmark", 30).ro and "api/mobile/pois" in access.method_text("landmark", 30).ro


@needs_data
def test_landmark_impact_endpoint():
    from app.main import app

    c = TestClient(app)
    j = c.get("/api/closures/cl_20261108_16dec/landmarks").json()
    assert j["total"] == 20 and j["losingNearestStop"] == sum(1 for i in j["items"] if i["losesService"])
    lost = [i for i in j["items"] if i["losesService"]]
    assert lost and lost[0]["nearestServed"]["stopId"] != lost[0]["nearestStop"]["stopId"]
    assert j["items"][0]["losesService"]  # the ones that lose come first
    assert j["provenance"][0]["note"].startswith("api/mobile/pois, preluat")
    assert c.get("/api/closures/nope/landmarks").status_code == 404
