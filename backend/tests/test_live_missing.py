"""O2: lines with no vehicle in our live recording (app/live/missing.py, GET /api/live/missing).

The proof case is the real recording: Sat 14 Nov 2026 06:00-10:41 flags line 23 only;
Fri 13 Nov 13:00-23:00 does not flag it. Those tests skip when the recording is absent.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.common.timeutil import parse_iso
from app.live import missing
from app.models.live_missing import MissingLines
from tests.conftest import DATA_DIR, needs_data

VEH = DATA_DIR / "live" / "vehicles"
SAT = [VEH / f"20261114-{h:02d}.jsonl.gz" for h in range(4, 9)]     # 06:00-10:59 Bucharest
FRI = [VEH / f"20261113-{h:02d}.jsonl.gz" for h in range(11, 21)]   # 13:00-22:59 Bucharest
needs_sat = pytest.mark.skipif(not all(p.is_file() for p in SAT), reason="no 14 Nov recording")
needs_fri = pytest.mark.skipif(not all(p.is_file() for p in FRI), reason="no 13 Nov recording")

SAT_FROM, SAT_TO = "2026-11-14T06:00:00+02:00", "2026-11-14T10:41:00+02:00"


# --- method, on hand-made snapshots ------------------------------------------------------

def _snap(ts: float, trips=(), route_dirs=(), healthy=True) -> missing.Snap:
    return missing.Snap(ts=ts, healthy=healthy, routes=frozenset(r for r, _ in route_dirs),
                        trips=frozenset(trips), route_dirs=frozenset(route_dirs))


def _trips(*rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["trip_id", "route_id", "direction_id", "start_ts", "end_ts"])


def test_compact_marks_stale_snapshots_unhealthy():
    fresh = missing._compact({"fetchedAt": "2026-11-14T08:00:09+00:00", "realtimeAgeSec": 120,
                              "vehicles": [{"routeId": "R_AB_23", "tripId": "t1", "directionId": 0}]})
    stale = missing._compact({"fetchedAt": "2026-11-14T08:00:24+00:00", "realtimeAgeSec": 121, "vehicles": []})
    unknown = missing._compact({"fetchedAt": "2026-11-14T08:00:39+00:00", "vehicles": []})
    assert fresh.healthy and fresh.route_dirs == {("R_AB_23", 0)} and fresh.trips == {"t1"}
    assert not stale.healthy and not unknown.healthy


def test_classify_trips_by_trip_id_route_direction_and_unknown():
    s, e = 0.0, 3600.0
    snaps = [_snap(600, trips={"late"}, route_dirs={("R1", 1)}),
             _snap(900, route_dirs={("R1", 0)}),
             _snap(1500, healthy=False, route_dirs={("R1", 1)})]
    trips = _trips(
        ("late", "R1", 1, 3000, 3300),    # its id was seen earlier in the window: a late vehicle
        ("dir0", "R1", 0, 800, 1000),     # same route and direction during its span
        ("dir1", "R1", 1, 1400, 1600),    # only an unhealthy snapshot in its span: not judged
        ("gone", "R1", 1, 850, 1000),     # healthy snapshot in its span, other direction only
        ("tail", "R1", 0, 3500, 3700),    # starts in the last 5 min of the window: too soon
    )
    assert missing.classify_trips(trips, snaps, s, e) == ["observed", "observed", "unknown", "missed", "unknown"]


# --- the proof case on the real recording ------------------------------------------------

@needs_data
@needs_sat
def test_saturday_flags_line_23_only():
    r = missing.detect(parse_iso(SAT_FROM), parse_iso(SAT_TO))
    MissingLines.model_validate(r)
    assert r["status"] == "ok" and r["recording"]["healthyShare"] >= missing.MIN_HEALTHY_SHARE
    flagged = [x for x in r["routes"] if x["state"] == "fara_vehicul"]
    assert [x["routeId"] for x in flagged] == ["R_AB_23"]
    l23 = flagged[0]
    assert (l23["shortName"], l23["mode"]) == ("23", "autobuz")
    assert (l23["tripsInService"], l23["tripsObserved"]) == (19, 0)
    assert l23["since"] == SAT_FROM and l23["lastSeenAt"] is None
    # the first trip in service with no vehicle (Banatim 05:55), at its first stop inside the window
    assert l23["firstMissedTrip"]["tripId"] == "23.1_WESB_T_01_02"
    assert l23["firstMissedTrip"]["scheduledTime"] >= SAT_FROM
    assert {p["version"] for p in r["provenance"]} >= {"4.31"}
    assert "20261114-04.jsonl.gz" in r["recording"]["files"]


@needs_data
@needs_sat
def test_saturday_trip_due_at_calderon_0920_has_no_vehicle():
    """The trip Albert waited for (facts.md, „Linia 23”): due at Liceul J. L. Calderon at 9:20."""
    start, end = parse_iso(SAT_FROM), parse_iso(SAT_TO)
    f = missing.gtfs.feed(start)
    trips, _ = missing.scheduled_trips(f, start, end)
    snaps, _ = missing.recorded(start, end)
    trips = trips.assign(result=missing.classify_trips(trips, snaps, start.timestamp(), end.timestamp()))
    assert trips[trips.route_id == "R_AB_23"].trip_id.nunique() == 19
    assert trips.route_id.nunique() == 47  # facts.md: 47 lines with trips in service 06:00-10:41
    row = trips[trips.trip_id == "23.1_WESB_T_01_09"].iloc[0]
    assert row.result == "missed"
    at = missing.trip_stop_time(f, row.trip_id, row.day, stop_id="398")
    assert at["stopName"] == "Liceul J. L. Calderon"
    assert at["scheduledTime"] == "2026-11-14T09:20:00+02:00"


@needs_data
@needs_fri
def test_friday_does_not_flag_line_23():
    r = missing.detect(parse_iso("2026-11-13T13:00:00+02:00"), parse_iso("2026-11-13T23:00:00+02:00"))
    assert r["status"] == "ok"
    assert "R_AB_23" not in {x["routeId"] for x in r["routes"]}
    assert not [x for x in r["routes"] if x["state"] == "fara_vehicul"]


@needs_data
def test_incomplete_recording_flags_nothing(monkeypatch):
    monkeypatch.setattr(missing, "recorded", lambda s, e: ([], []))
    r = missing.detect(parse_iso(SAT_FROM), parse_iso(SAT_TO))
    assert r["status"] == "inregistrare_incompleta"
    assert r["routes"] == [] and r["byMode"] == []
    assert r["recording"]["healthyShare"] == 0


# --- API ---------------------------------------------------------------------------------

@needs_data
@needs_sat
def test_api_window_and_prepared_case(client):
    r = client.get("/api/live/missing", params={"from": SAT_FROM, "to": SAT_TO})
    assert r.status_code == 200
    body = r.json()
    assert body["case"] is None
    assert [x["routeId"] for x in body["routes"] if x["state"] == "fara_vehicul"] == ["R_AB_23"]
    modes = {m["mode"]: m for m in body["byMode"]}
    assert set(modes) == {"autobuz", "troleibuz", "tramvai"}
    assert modes["autobuz"]["tripsWithNoVehicle"] >= 19

    c = client.get("/api/live/missing", params={"case": "case_l23"}).json()
    assert c["case"] == {"id": "case_l23", "label": {"ro": "înregistrat 14 nov", "en": "recorded 14 Nov"}}
    assert c["window"] == {"start": SAT_FROM, "end": SAT_TO}
    assert c["routes"] == body["routes"]

    o = client.get("/api/overview").json()["missingLines"]
    assert o["prepared"]["count"] == 1 and o["prepared"]["rows"][0]["routeId"] == "R_AB_23"
    assert o["live"] is None or o["live"]["status"] in ("ok", "inregistrare_incompleta")


@needs_data
def test_api_rejects_bad_windows(client):
    assert client.get("/api/live/missing", params={"case": "nope"}).status_code == 422
    assert client.get("/api/live/missing", params={"from": "ieri"}).status_code == 422
    assert client.get("/api/live/missing", params={"from": SAT_TO, "to": SAT_FROM}).status_code == 422
    assert client.get("/api/live/missing", params={"from": "2026-11-13T00:00:00+02:00",
                                                   "to": SAT_TO}).status_code == 422
