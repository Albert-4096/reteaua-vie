"""L0 observed timetable on a tiny synthetic recording and GTFS built here (no recording files copied)."""

from __future__ import annotations

import gzip
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config

LAT = 45.75
LON0 = 21.20
DLON_PER_M = 0.0193 / 1500   # ~1500 m of longitude at 45.75 N
STOPS = [("A", 0), ("B", 500), ("C", 1000), ("D", 1500)]


def _gtfs_zip(path):
    files = {
        "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\nX,Test,https://example.org,Europe/Bucharest\n",
        "feed_info.txt": "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date,feed_version\n"
                         "T,https://example.org,ro,20261101,20261231,9.99\n",
        "routes.txt": "route_id,route_short_name,route_type\nR_T_1,1,0\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\n" + "".join(
            f"{s},{s},{LAT},{LON0 + m * DLON_PER_M:.7f}\n" for s, m in STOPS),
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                        "S_FRI,0,0,0,0,1,0,0,20261101,20261231\n",
        "calendar_dates.txt": "service_id,date,exception_type\n",
        "trips.txt": "route_id,service_id,trip_id,trip_headsign,direction_id,shape_id\n"
                     "R_T_1,S_FRI,T1,D,0,SH\nR_T_1,S_FRI,T2,D,0,SH\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n" + "".join(
            f"T1,10:0{2 * i}:00,10:0{2 * i}:00,{s},{i + 1}\n" for i, (s, _) in enumerate(STOPS)) + "".join(
            f"T2,{h},{h},{s},{i + 1}\n" for i, ((s, _), h) in
            enumerate(zip(STOPS, ["23:58:00", "24:00:00", "24:02:00", "24:04:00"]))),
        "shapes.txt": "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n" + "".join(
            f"SH,{LAT},{LON0 + m * DLON_PER_M:.7f},{i + 1}\n" for i, m in enumerate(range(0, 1501, 250))),
    }
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)


def _state(u: float) -> tuple[float, int, str]:
    """(metres along the line, stopSequence, status) of the vehicle u seconds after its first departure."""
    if u < 30:
        return 0.0, 1, "STOPPED_AT"
    if u < 120:
        return 500 * (u - 30) / 90, 2, "IN_TRANSIT_TO"
    if u < 165:
        return 500.0, 2, "STOPPED_AT"
    if u < 345:
        s = 500 + 1000 * (u - 165) / 180
        return s, (3 if s < 1000 else 4), "IN_TRANSIT_TO"
    return 1500.0, 4, "STOPPED_AT"


def _vehicle(trip: str, t0: float, poll: float) -> dict | None:
    u = (poll - t0) // 30 * 30          # the vehicle reports every 30 s; we poll every 15 s
    if u < -120 or u > 400:
        return None
    s, seq, status = _state(u)
    return {"id": "V1", "routeId": "R_T_1", "tripId": trip, "directionId": 0, "headsign": "D",
            "lat": LAT, "lon": LON0 + s * DLON_PER_M, "bearing": 90, "speed": 0 if status == "STOPPED_AT" else 8,
            "stopId": STOPS[seq - 1][0], "stopSequence": seq, "status": status,
            "delaySec": int(u - 120 * (seq - 1)), "updatedAt": int(t0 + u), "wheelchair": True}


def _recording(live, trips: list[tuple[str, datetime]], hours: list[datetime]):
    d = live / "vehicles"
    d.mkdir(parents=True)
    for hour in hours:
        lines = []
        t = hour
        while t < hour + timedelta(hours=1):
            vs = [v for trip, t0 in trips if (v := _vehicle(trip, t0.timestamp(), t.timestamp()))]
            lines.append(json.dumps({"fetchedAt": t.isoformat(), "vehicles": vs}))
            t += timedelta(seconds=15)
        with gzip.open(d / f"{hour:%Y%m%d-%H}.jsonl.gz", "wt", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


UTC = timezone.utc
T1_DEP = datetime(2026, 11, 13, 8, 0, tzinfo=UTC)      # 10:00 Bucharest, Friday
T2_DEP = datetime(2026, 11, 13, 21, 58, tzinfo=UTC)    # 23:58 Bucharest, Friday; ends after midnight


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    data = tmp_path / "data"
    live = data / "live"
    data.mkdir()
    _gtfs_zip(data / "smtt-timisoara-ro_2026-11-11.zip")
    hours = [datetime(2026, 11, 13, h, tzinfo=UTC) for h in (7, 8, 9, 21, 22)]
    _recording(live, [("T1", T1_DEP), ("T2", T2_DEP)], hours)
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("LIVE_DIR", str(live))
    monkeypatch.setenv("ENV_FILE", "")
    config.get_settings.cache_clear()
    from app.observed import build, store, summary

    build._DAY_SHA.clear()
    store._memo.clear()
    summary._memo.clear()
    yield data
    build._DAY_SHA.clear()
    store._memo.clear()
    summary._memo.clear()
    config.get_settings.cache_clear()


def test_build_events_segments_and_incremental(synthetic):
    from app.observed import build, store

    assert build.build() == 5          # the recorder is long stopped: every hour is built
    assert build.build() == 0          # an hour already built is not rebuilt
    ev = store.events().sort_values(["trip_id", "stop_sequence"])
    t1 = ev[ev["trip_id"] == "T1"].set_index("stop_sequence")
    base = T1_DEP.timestamp()
    assert list(t1.index) == [1, 2, 3, 4]
    # first stop: departure only (midpoint of the 0 s / 30 s reports); last stop: arrival only
    assert pd.isna(t1.loc[1, "arr"]) and t1.loc[1, "dep"] == base + 15
    assert t1.loc[2, "arr"] == base + 105 and t1.loc[2, "dep"] == base + 165 and t1.loc[2, "dwell_sec"] == 60
    assert t1.loc[2, "delay_sec"] == -15 and not t1.loc[2, "interpolated"]
    # C was passed between two reports: interpolated along the shape, exactly at 255 s
    assert t1.loc[3, "interpolated"] and abs(t1.loc[3, "arr"] - (base + 255)) < 1 and pd.isna(t1.loc[3, "dwell_sec"])
    assert t1.loc[4, "arr"] == base + 345 and pd.isna(t1.loc[4, "dep"])
    seg = store.segments()
    s1 = seg[seg["trip_id"] == "T1"].sort_values("from_sequence")
    assert [round(x) for x in s1["run_sec"]] == [90, 90, 90]
    assert set(s1["day_type"]) == {"fri"} and set(s1["hour_local"]) == {10}
    # the trip after midnight keeps its Friday service date; its runs after 00:00 are Saturday
    t2 = ev[ev["trip_id"] == "T2"]
    assert set(t2["service_date"]) == {"2026-11-13"} and len(t2) == 4
    s2 = seg[seg["trip_id"] == "T2"].sort_values("from_sequence")
    assert list(zip(s2["day_type"], s2["hour_local"])) == [("fri", 23), ("sat", 0), ("sat", 0)]
    assert t2["delay_sec"].abs().max() < 16


def test_gap_longer_than_max_gives_no_event(synthetic):
    from app.observed import build

    reports, _ = build.parse_file(synthetic / "live" / "vehicles" / "20261113-08.jsonl.gz")
    t = reports["t"] - T1_DEP.timestamp()
    cut = reports[~((t > 180) & (t < 400))]       # silence from 180 s to 400 s: C and D unseen
    ev, _seg, _ = build.compute(cut[cut["trip"] == "T1"])
    assert sorted(ev["stop_sequence"]) == [1, 2]


def test_pending_waits_for_the_next_hour(synthetic):
    from app.observed import build

    newest = datetime(2026, 11, 13, 22, 59, 45, tzinfo=UTC)
    stems = [build.stem(h) for _, h in build.pending_hours(now_utc=newest + timedelta(seconds=30))]
    assert stems == ["20261113-07", "20261113-08", "20261113-09", "20261113-21"]   # 22 is open


def test_summary_endpoint(synthetic):
    from app.observed import api_observed, build

    build.build()
    app = FastAPI()
    app.include_router(api_observed.router, prefix="/api")
    body = TestClient(app).get("/api/observed/summary").json()
    assert body["stopEvents"] == 8 and body["interpolatedEvents"] == 2 and body["trips"] == 2
    assert body["quality"]["tripsWith80PctStops"] == 2 and body["quality"]["tripsAfterMidnight"] == 1
    assert body["quality"]["medianAbsDelayDiffSec"] is not None
    assert body["label"]["ro"].startswith("din ") and "vin." in body["label"]["ro"]
    assert body["hours"]["from"].endswith("+02:00") and body["provenance"][1]["version"] == "9.99"
