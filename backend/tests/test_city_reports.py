from fastapi.testclient import TestClient

from app.city_reports import core
from tests.conftest import needs_data


def test_category_validation():
    assert core.categories_for(None) == core.MOBILITY
    assert core.categories_for("Străzi și trotuare") == ("Străzi și trotuare",)


@needs_data
def test_zones_stops_and_road_issues():
    from app.main import app

    c = TestClient(app)
    z = c.get("/api/reports/zones").json()
    assert len(z["rows"]) == 40 and z["kind"] == "zones"
    assert "ultimele 2 zile" in z["label"]["ro"]
    assert z["reportsRecorded"] >= sum(r["total"] for r in z["rows"]) > 0
    for r in z["rows"]:
        assert r["open"] <= r["total"] and r["distinctProblems"] <= r["total"]
        assert "descriere" not in r and "text" not in r
    assert c.get("/api/reports/zones?category=nope").status_code == 422
    s = c.get("/api/reports/stops?category=Străzi și trotuare&radius=50").json()
    assert s["radiusMeters"] == 50 and all(r["location"] for r in s["rows"])
    assert c.get("/api/reports/stops?radius=1").status_code == 422
    csv = c.get("/api/reports/zones.csv")
    assert csv.content.startswith(b"\xef\xbb\xbf") and ";" in csv.text.splitlines()[0]
    ri = c.get("/api/road-issues?limit=3").json()
    assert ri["matchMeters"] == 15 and len(ri["segments"]) <= 3
    assert ri["potholesOnCorridors"] <= ri["potholesRecorded"]
    assert all(x["potholes"] >= 1 and x["departuresPerDay"] > 0 for x in ri["segments"])
    lay = c.get("/api/layers/road_issues").json()
    assert lay["layer"] == "road_issues" and len(lay["features"]) == ri["segmentsWithReports"]
    assert lay["features"][0]["geometry"]["type"] == "LineString"
