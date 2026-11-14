"""R20: traveller problem reports (fixed categories, counts only). State goes to a temp dir."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.checkin import store
from app.cityapp import status
from app.common.errors import ApiError
from app.config import TZ, real_now
from app.travellers import service
from app.travellers.models import ReportInput
from tests.conftest import needs_data


@pytest.fixture(autouse=True)
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_dir", lambda: (tmp_path.mkdir(exist_ok=True), tmp_path)[1])
    service._all.clear()
    service._by.clear()


def rep(device="phone-aaaaaaaa1", cat="bus_did_not_come", stop="356", **kw):
    return ReportInput(stopId=stop, category=cat, deviceKey=device, **kw)


@needs_data
def test_report_is_counted_once_per_phone_stop_category_and_keeps_no_identity():
    assert service.accept(rep()).counted is True
    assert service.accept(rep()).counted is False
    assert service.accept(rep(cat="poster_wrong")).counted is True
    row = service.rows()[0]
    assert set(row) == {"receivedAt", "stopId", "category", "routeId", "device"} and "phone-aaaaaaaa1" not in str(row)
    ack = service.accept(rep("phone-bbbbbbbb2"))
    assert "nu a fost trimis Primăriei" in ack.note.ro and ack.provenance


@needs_data
def test_unknown_stop_far_position_wrong_route_and_free_text_are_refused():
    with pytest.raises(ApiError) as e:
        service.accept(rep(stop="999999"))
    assert e.value.status_code == 404
    with pytest.raises(ApiError) as e:
        service.accept(rep(lat=45.80, lon=21.30))
    assert e.value.code == "FAR_FROM_STOP"
    with pytest.raises(ApiError) as e:
        service.accept(rep(routeId="R_TV_4"))
    assert e.value.code == "ROUTE_NOT_AT_STOP"
    with pytest.raises(Exception):
        ReportInput(stopId="356", category="my own words", deviceKey="phone-aaaaaaaa1")
    assert service.rows() == []


@needs_data
def test_position_at_the_stop_is_accepted_and_not_stored():
    assert service.accept(rep(lat=45.7454, lon=21.21503)).counted
    assert "45.74" not in str(service.rows())


def test_rate_limit_per_phone():
    ok = [service.allow("s", "d", now=float(i)) for i in range(6)]
    assert ok == [True] * service.MAX_PER_DEVICE_MIN + [False] * 2


@needs_data
def test_summary_counts_distinct_phones_and_the_s1_signal():
    service.accept(rep("phone-aaaaaaaa1"))
    service.accept(rep("phone-bbbbbbbb2"))
    service.accept(rep("phone-bbbbbbbb2", cat="accessibility"))
    now = real_now()
    s = service.summary(now - timedelta(hours=1), now + timedelta(minutes=1))
    assert s.travellers == 2 and s.stops[0].travellers == 2
    assert {c.category: c.travellers for c in s.stops[0].byCategory} == {"bus_did_not_come": 2, "accessibility": 1}
    st = status.stop_status("356", now)
    assert st.travellerReports.travellers == 2 and "Semnalat de 2 călători (neconfirmat)" in st.sentence.ro
    assert status.stop_status("356", now - timedelta(days=2)).travellerReports is None


@needs_data
def test_retention_folds_old_rows_into_counts():
    old = datetime.now(TZ) - timedelta(hours=60)
    with store.locked():
        store._write(service._name(old), [{"receivedAt": old.isoformat(), "stopId": "356", "category": "poster_wrong",
                                           "routeId": None, "device": "x"}])
    service._purge(datetime.now(TZ))
    assert service.rows() == []
    assert store._read("reportcounts.json", {})[old.isoformat()[:10]]["356"] == {"poster_wrong": 1}


@needs_data
def test_reports_reach_the_o2_rows_as_a_labelled_signal():
    from app.live import missing
    service.accept(rep("phone-aaaaaaaa1", routeId="R_AB_32"))
    now = real_now()
    win = {"start": (now - timedelta(hours=1)).isoformat(), "end": (now + timedelta(minutes=1)).isoformat()}
    res = missing.with_decisions({"window": win, "routes": [{"routeId": "R_AB_32", "state": "partial"},
                                                            {"routeId": "R_AB_33", "state": "partial"}]})
    a, b = res["routes"]
    assert a["travellerReports"]["travellers"] == 1 and "semnalat de 1 călător (neconfirmat)" in a["travellerReports"]["label"]["ro"]
    assert b["travellerReports"] is None


@needs_data
def test_http_post_is_mounted(client):
    r = client.post("/api/problem-report", json={"stopId": "356", "category": "poster_wrong", "deviceKey": "phone-httpaaaa1"})
    assert r.status_code == 200 and r.json()["counted"] is True
    assert client.post("/api/problem-report", json={"stopId": "356", "category": "free text", "deviceKey": "phone-httpaaaa1"}).status_code == 422
