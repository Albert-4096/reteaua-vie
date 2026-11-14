"""A13 on a synthetic snapshot and trip: no recording, no City Hall data."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from google.transit import gtfs_realtime_pb2 as rt

from app.analytics import eta
from app.config import TZ

AT = datetime(2026, 11, 13, 14, 0, 0, tzinfo=TZ)
BASE = datetime(2026, 11, 13, tzinfo=TZ).timestamp()


def _setup(monkeypatch, vehicles, chosen="persist"):
    st = pd.DataFrame({"trip_id": ["t1"] * 4, "stop_id": ["a", "b", "c", "d"], "stop_sequence": [1, 2, 3, 4],
                       "arr_sec": [14 * 3600 - 300, 14 * 3600 + 300, 14 * 3600 + 900, 14 * 3600 + 1500]})
    snap = {"fetchedAt": AT.isoformat(), "vehicles": vehicles}
    monkeypatch.setattr(eta.vehicles, "newest_snapshot", lambda: snap)
    monkeypatch.setattr(eta.vehicles, "snapshot_time", lambda s: AT)
    monkeypatch.setattr(eta.gtfs, "feed", lambda at=None: type("F", (), {"stop_times": st})())
    monkeypatch.setattr(eta.store, "coverage", lambda: {"first": AT, "last": AT})
    monkeypatch.setattr(eta.accessibility, "_route_names", lambda: {"R1": ("1", "tram")})
    monkeypatch.setattr(eta, "backtest", lambda: {"chosen": chosen})
    eta._memo.pop("trips", None)
    return AT.timestamp()


def _v(age, delay=120, seq=2, status="IN_TRANSIT_TO"):
    return {"id": "V1", "tripId": "t1", "routeId": "R1", "directionId": 0, "stopSequence": seq, "status": status,
            "delaySec": delay, "updatedAt": int(AT.timestamp()) - age}


def test_eta_is_schedule_plus_delay_for_future_stops_only(monkeypatch):
    now = _setup(monkeypatch, [_v(10)])
    d = eta.build(now_ts=now + 5)
    t = d["trips"][0]
    assert [u["stopId"] for u in t["updates"]] == ["b", "c", "d"]
    assert t["updates"][0]["delaySec"] == 120
    assert t["updates"][0]["_arr"] == int(BASE + 14 * 3600 + 300 + 120)


def test_stopped_vehicle_gets_only_the_stops_after_it(monkeypatch):
    now = _setup(monkeypatch, [_v(10, status="STOPPED_AT")])
    assert [u["stopId"] for u in eta.build(now_ts=now)["trips"][0]["updates"]] == ["c", "d"]


def test_no_eta_without_a_recent_report(monkeypatch):
    now = _setup(monkeypatch, [_v(eta.MAX_AGE_SEC + 5)])
    d = eta.build(now_ts=now)
    assert d["trips"] == [] and d["skipped"] == 1


def test_stale_snapshot_gives_an_empty_feed(monkeypatch):
    now = _setup(monkeypatch, [_v(5)])
    assert eta.build(now_ts=now + eta.MAX_STALE_SNAPSHOT_SEC + 10)["trips"] == []


def test_timetable_predictor_adds_no_delay_and_protobuf_round_trips(monkeypatch):
    now = _setup(monkeypatch, [_v(5)], chosen="timetable")
    d = eta.build(now_ts=now)
    assert d["trips"][0]["updates"][0]["delaySec"] == 0
    msg = rt.FeedMessage()
    msg.ParseFromString(eta.feed_bytes(d))
    tu = msg.entity[0].trip_update
    assert msg.header.gtfs_realtime_version == "2.0" and tu.trip.trip_id == "t1"
    assert tu.stop_time_update[0].stop_id == "b" and tu.stop_time_update[0].arrival.time > 0


def test_times_strictly_increase_even_when_the_timetable_repeats_a_minute(monkeypatch):
    now = _setup(monkeypatch, [_v(5)])
    import pandas as pd
    st = pd.DataFrame({"trip_id": ["t1"] * 3, "stop_id": ["a", "b", "c"], "stop_sequence": [1, 2, 3],
                       "arr_sec": [14 * 3600, 14 * 3600, 14 * 3600]})
    monkeypatch.setattr(eta.gtfs, "feed", lambda at=None: type("F", (), {"stop_times": st})())
    eta._memo.pop("trips", None)
    t = [u["_arr"] for u in eta.build(now_ts=now)["trips"][0]["updates"]]
    assert t == sorted(set(t)) and len(t) >= 2
