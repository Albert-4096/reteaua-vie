from fastapi.testclient import TestClient

from tests.conftest import needs_data
from app.dataquality import checks


def test_notice_tokens_drop_glued_si():
    assert checks._notice_tokens("liniile 33B si 46 si S8") == ["33b", "46", "s8"]


@needs_data
def test_data_quality_rows_and_csv():
    from app.main import app

    c = TestClient(app)
    j = c.get("/api/data-quality").json()
    rows = {r["id"]: r for r in j["rows"]}
    assert {"gtfs_wheelchair", "osm_wheelchair", "live_delay", "timpark_unchecked", "notice_lines_not_in_gtfs",
            "smtt_menu_missing", "gtfs_structure", "mobilitydata_validator"} <= set(rows)
    assert rows["smtt_menu_missing"]["basis"] == "manual" and rows["mobilitydata_validator"]["status"] == "indisponibil"
    assert rows["gtfs_wheelchair"]["found"] == rows["gtfs_wheelchair"]["of"] > 0
    assert any("S8" in d for d in rows["notice_lines_not_in_gtfs"]["detail"])
    for r in j["rows"]:
        assert r["owner"] and r["unlocks"]["ro"] and r["request"]["ro"]
        assert "greșit" not in (r["request"]["ro"] + r["title"]["ro"]).lower()
    csv = c.get("/api/data-quality.csv")
    assert csv.status_code == 200 and csv.content.startswith(b"\xef\xbb\xbf") and csv.text.count("\n") >= 9
