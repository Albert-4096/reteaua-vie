"""C1 check-in and C2 service confirmation. State goes to a temp dir; the live recording is faked."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.checkin import confirm, service, store
from app.checkin.models import CheckinInput
from app.common.errors import ApiError
from app.config import TZ
from app.live import missing
from tests.conftest import needs_data

AT = "2026-11-14T08:30:00+02:00"


@pytest.fixture(autouse=True)
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_dir", lambda: (tmp_path.mkdir(exist_ok=True), tmp_path)[1])
    service._all.clear()
    service._by.clear()


def body(device="phone-aaaaaaaa1", at=AT, **kw):
    return CheckinInput(stickerId="test-l23", at=at, deviceKey=device, **kw)


@needs_data
def test_checkin_resolves_a_trip_and_marks_simulation():
    ack = service.accept(body())
    assert ack.routeId == "R_AB_23" and ack.tripId.startswith("23.") and ack.method == "time"
    assert ack.simulated and ack.label.ro == "simulare" and ack.provenance
    row = store.raw_rows()[0]
    assert set(row) == {"at", "receivedAt", "stickerId", "routeId", "directionId", "tripId", "stopId", "device", "simulated",
                        "method", "tripStart", "prevStart", "nextStart"}
    assert "phone-aaaaaaaa1" not in str(row) and len(row["device"]) == 16


@needs_data
def test_far_position_unknown_sticker_future_and_bad_pair():
    with pytest.raises(ApiError) as e:
        service.accept(body(lat=45.80, lon=21.30))
    assert e.value.code == "FAR_FROM_ROUTE" and "departe de traseu" in e.value.message
    with pytest.raises(ApiError) as e:
        service.accept(CheckinInput(stickerId="nope", deviceKey="phone-aaaaaaaa1"))
    assert e.value.status_code == 404
    with pytest.raises(ApiError):
        service.accept(body(lat=45.76))
    with pytest.raises(ApiError):
        service.accept(body(at=(datetime.now(TZ) + timedelta(hours=1)).isoformat()))
    assert store.raw_rows() == []


@needs_data
def test_position_near_route_is_accepted_with_distance():
    ack = service.accept(body(lat=45.76636, lon=21.2446))
    assert ack.distanceToRouteMeters is not None and ack.distanceToRouteMeters < 300


def test_rate_limit_per_device():
    ok = [service.allow("s", "d", now=float(i)) for i in range(8)]
    assert ok == [True] * service.MAX_PER_DEVICE_MIN + [False] * (8 - service.MAX_PER_DEVICE_MIN)


def test_retention_folds_old_days_into_counts():
    old = datetime.now(TZ) - timedelta(hours=60)
    store.add_row({"at": old.isoformat(), "receivedAt": old.isoformat(), "stickerId": "s", "routeId": "R_AB_23", "directionId": 0,
                   "tripId": "t1", "stopId": "536", "device": "x", "simulated": True}, old)
    assert store.raw_rows()
    store.purge(datetime.now(TZ))
    assert store.raw_rows() == []
    day = old.astimezone(TZ).isoformat()[:10]
    assert store.archived_counts()[day]["R_AB_23"]["t1"]["count"] == 1
    assert "device" not in str(store.archived_counts())


def _fake_recording(monkeypatch, routes=()):
    from app.live.missing import Snap
    snap = Snap(ts=datetime(2026, 11, 14, 8, 30, tzinfo=TZ).timestamp(), healthy=True, routes=frozenset(routes),
                trips=frozenset(), route_dirs=frozenset())
    monkeypatch.setattr(missing, "recorded", lambda a, b: ([snap], ["f"]))


@needs_data
def test_two_phones_on_one_trip_confirm_service_without_gps(monkeypatch):
    _fake_recording(monkeypatch)
    service.accept(body("phone-aaaaaaaa1", "2026-11-14T08:30:00+02:00"))
    assert confirm.confirmations(datetime(2026, 11, 14, 6, tzinfo=TZ), datetime(2026, 11, 14, 11, tzinfo=TZ)) == {}
    service.accept(body("phone-bbbbbbbb2", "2026-11-14T08:31:00+02:00"))
    conf = confirm.confirmations(datetime(2026, 11, 14, 6, tzinfo=TZ), datetime(2026, 11, 14, 11, tzinfo=TZ))
    c = conf["R_AB_23"]
    assert c.travelers == 2 and c.simulated and "confirmat de 2 călători" in c.label.ro and "simulare" in c.label.ro
    rows = confirm.annotate([{"routeId": "R_AB_23"}, {"routeId": "R_AB_24"}],
                            {"start": "2026-11-14T06:00:00+02:00", "end": "2026-11-14T11:00:00+02:00"})
    assert rows[0]["serviceConfirmation"]["travelers"] == 2 and rows[1]["serviceConfirmation"] is None


@needs_data
def test_a_vehicle_in_the_recording_or_one_phone_gives_no_confirmation(monkeypatch):
    _fake_recording(monkeypatch, routes=["R_AB_23"])
    service.accept(body("phone-aaaaaaaa1", "2026-11-14T08:30:00+02:00"))
    service.accept(body("phone-bbbbbbbb2", "2026-11-14T08:31:00+02:00"))
    assert confirm.confirmations(datetime(2026, 11, 14, 6, tzinfo=TZ), datetime(2026, 11, 14, 11, tzinfo=TZ)) == {}
    monkeypatch.setattr(missing, "recorded", lambda a, b: ([], []))   # no recording: no claim either
    assert confirm.confirmations(datetime(2026, 11, 14, 6, tzinfo=TZ), datetime(2026, 11, 14, 11, tzinfo=TZ)) == {}


@needs_data
def test_http_post_and_counts(client):
    r = client.post("/api/checkin", json={"stickerId": "test-l23", "at": AT, "deviceKey": "phone-httpaaaa1"})
    assert r.status_code == 200, r.text
    c = client.get("/api/checkins", params={"routeId": "R_AB_23", "from": "2026-11-14T06:00:00+02:00", "to": "2026-11-14T11:00:00+02:00"}).json()
    assert c["total"] == 1 and c["simulated"] == 1 and c["lines"][0]["trips"][0]["distinctDevices"] == 1
    assert "simulare" in c["note"]["ro"]
    assert client.post("/api/checkin", json={"stickerId": "test-l23", "deviceKey": "x"}).status_code == 422


@needs_data
def test_two_phones_three_minutes_apart_on_adjacent_trips_still_confirm(monkeypatch):
    _fake_recording(monkeypatch)
    a = service.accept(body("phone-aaaaaaaa1", "2026-11-14T08:30:00+02:00"))
    b = service.accept(body("phone-bbbbbbbb2", "2026-11-14T08:33:00+02:00"))
    assert a.tripId != b.tripId          # the timetable split them: the case this guards
    c = confirm.confirmations(datetime(2026, 11, 14, 6, tzinfo=TZ), datetime(2026, 11, 14, 11, tzinfo=TZ))["R_AB_23"]
    assert c.travelers == 2 and len(c.trips) == 2 and "confirmat de 2 călători" in c.label.ro


def test_pinned_trips_group_only_when_neighbours():
    a = {"tripId": "t1", "method": "position", "tripStart": 100, "prevStart": 50, "nextStart": 200}
    assert confirm._same_group(a, {"tripId": "t2", "method": "position", "tripStart": 200})
    assert not confirm._same_group(a, {"tripId": "t3", "method": "position", "tripStart": 300})
    assert confirm._same_group(a, {"tripId": "t3", "method": "time", "tripStart": 300})
