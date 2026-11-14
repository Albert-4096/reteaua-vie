from datetime import datetime

from fastapi.testclient import TestClient

from app.config import TZ
from app.m6_parking import paid
from tests.conftest import needs_data

SCHEDULE = {"weekdays": [8, 20], "saturday": {"green": [8, 17]}}


def dt(d, h=0):
    return datetime(2026, 11, d, h, tzinfo=TZ)


def test_paid_hours_follow_the_schedule():
    # Fri 13 Nov 00:00 -> Mon 16 Nov 00:00: Friday 12 h; Saturday green 9 h, others 0; Sunday 0
    assert paid._hours(paid._intervals(dt(13), dt(16), "yellow", SCHEDULE)) == 12.0
    assert paid._hours(paid._intervals(dt(13), dt(16), "green", SCHEDULE)) == 21.0
    # a window inside the paid day counts only its own hours
    assert paid._hours(paid._intervals(dt(13, 10), dt(13, 12), "red", SCHEDULE)) == 2.0
    assert paid._hours(paid._intervals(dt(15), dt(16), "green", SCHEDULE)) == 0.0  # Sunday = 0


def test_union_does_not_double_count():
    a = paid._intervals(dt(13), dt(14), "yellow", SCHEDULE)
    b = paid._intervals(dt(13), dt(14), "blue", SCHEDULE)
    assert paid._hours(paid._union([a, b])) == 12.0


@needs_data
def test_paid_parking_endpoint_and_csv():
    from app.main import app

    c = TestClient(app)
    j = c.get("/api/closures/cl_20261102_mocioni/paid-parking").json()
    assert j["streets"]["count"] > 0 and j["streets"]["meters"] > 0 and j["paidHours"] > 0
    assert "ore plătite" in j["noticeLine"]["ro"]
    assert "Fără lei" in j["note"]["ro"] and "sărbătorile legale" in j["note"]["ro"]
    narrow = c.get("/api/closures/cl_20261102_mocioni/paid-parking?start=2026-11-09T10:00:00%2B02:00&end=2026-11-09T12:00:00%2B02:00").json()
    assert narrow["paidHours"] == 2.0
    assert c.get("/api/closures/cl_20261102_mocioni/paid-parking?start=2026-11-09T10:00:00%2B02:00&end=2026-11-09T09:00:00%2B02:00").status_code == 422
    csv = c.get("/api/closures/cl_20261102_mocioni/paid-parking.csv")
    assert csv.content.startswith(b"\xef\xbb\xbf") and csv.text.count("\n") == j["streets"]["count"] + j["lots"]["count"] + 1
    assert c.get("/api/closures/nope/paid-parking").status_code == 404
