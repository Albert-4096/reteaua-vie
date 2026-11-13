"""M1 core on the real data: stop matching, analysis, decisions, impact, conflicts."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date

import pytest
from shapely.ops import substring

from app.common import gtfs
from app.common.geo import to_geojson, to_wgs84
from tests.conftest import DATA_DIR, needs_data

pytestmark = needs_data

WINDOW = {"start": "2026-11-08T10:00:00+02:00", "end": "2026-11-08T18:00:00+02:00"}  # Sunday


def _segment_16dec() -> dict:
    """Bd. 16 Decembrie 1989 from Piața Mocioni (stop 63) to Piața Maria (stop 59), along tram line 2 dir 0."""
    from app.m1_disruption import matching as m

    path = m.path_metric("R_TV_2", 0)
    a, b = path.project(m.stop_metric("63")), path.project(m.stop_metric("59"))
    return to_geojson(to_wgs84(substring(path, a - 20, b + 20)))


def _drawn(direction: str) -> dict:
    return {"id": "t", "title": {"ro": "t"}, "kind": "drawn", "geometry": _segment_16dec(), "bufferMeters": 30,
            "direction": direction, "window": WINDOW, "routeIds": None, "routeActions": None}


def _keys(rows: list[dict], mode_prefix: str = "R_TV_") -> set[tuple[str, str, int]]:
    return {(r["stopId"], r["routeId"], r["directionId"]) for r in rows if r["routeId"].startswith(mode_prefix)}


def test_drawn_segment_finds_tram_stops_in_the_drawn_direction():
    from app.m1_disruption import matching as m

    along = _keys(m.match_drawn(_drawn("along")))
    # trams that run Mocioni -> Piața Maria (direction 0 of lines 1, 2, 8) stop at 63 and 59
    assert {("59", "R_TV_2", 0), ("63", "R_TV_2", 0), ("59", "R_TV_1", 0), ("59", "R_TV_8", 0)} <= along
    assert all(d == 0 for _, _, d in along)
    against = _keys(m.match_drawn(_drawn("against")))
    assert ("62", "R_TV_2", 1) in against
    assert all(d == 1 for _, _, d in against)
    both = _keys(m.match_drawn(_drawn("both")))
    assert along | against == both


def test_drawn_rows_have_reasons_and_confidence():
    from app.m1_disruption import matching as m

    rows = {(r["stopId"], r["routeId"], r["directionId"]): r for r in m.match_drawn(_drawn("along"))}
    r = rows[("59", "R_TV_2", 0)]
    assert r["reasons"][:3] == ["IN_BUFFER", "ON_ROUTE_PATH", "DIRECTION_MATCH"]
    assert r["confidence"] == 0.85 and r["state"] == "affected"
    assert r["location"][0] == pytest.approx(21.2186, abs=1e-3)  # [lon, lat]
    edge = [x for x in rows.values() if "EDGE_OF_BUFFER" in x["reasons"]]
    assert all(x["state"] == "unsure" and x["confidence"] == 0.65 for x in edge)


def test_whole_line_suspended_gives_every_line_4_stop():
    from app.m1_disruption import matching as m

    closure = {"kind": "notice", "routeActions": [
        {"routeId": "R_TV_4", "directionId": None, "action": "suspended"}]}
    rows, unresolved = m.rows_from_actions(closure)
    expected = {(s, "R_TV_4", d) for d in (0, 1) for s in gtfs.stop_order("R_TV_4", d)}
    assert unresolved == []
    assert {(r["stopId"], r["routeId"], r["directionId"]) for r in rows} == expected
    assert len(expected) == 46
    assert all(r["confidence"] == 0.9 and r["state"] == "affected" for r in rows)


def test_section_input_by_line_fills_geometry():
    from app.m1_disruption import matching as m

    action = {"routeId": "R_TV_4", "directionId": 0, "action": "suspended", "fromStopId": "86", "toStopId": "55"}
    per_dir, _, _ = m.action_stops(action)
    assert per_dir == {0: ["86", "61", "57", "55"]}
    geom = m.geometry_from_actions([action])
    assert geom["type"] == "LineString" and len(geom["coordinates"]) >= 2
    # both directions: the opposite side maps to the stops across the street
    per_dir, _, _ = m.action_stops({**action, "directionId": None})
    assert per_dir[1] == ["56", "58", "60", "85"]


def _csv_count(stop_id: str, route_id: str, direction_id: int, day: date, t0: str, t1: str, path=None) -> int:
    """Second method: plain csv over the GTFS zip, no pandas and no index."""
    path = path or gtfs.feed_path()
    with zipfile.ZipFile(path) as z:
        def rows(name):
            return csv.DictReader(io.StringIO(z.read(name).decode("utf-8-sig")))

        ymd = day.strftime("%Y%m%d")
        wd = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")[day.weekday()]
        services = {c["service_id"] for c in rows("calendar.txt")
                    if c[wd] == "1" and c["start_date"] <= ymd <= c["end_date"]}
        for cd in rows("calendar_dates.txt"):
            if cd["date"] == ymd:
                (services.add if cd["exception_type"] == "1" else services.discard)(cd["service_id"])
        trips = {t["trip_id"] for t in rows("trips.txt") if t["route_id"] == route_id
                 and int(t["direction_id"] or 0) == direction_id and t["service_id"] in services}
        last: dict[str, int] = {}
        hits = []
        for st in rows("stop_times.txt"):
            if st["trip_id"] not in trips:
                continue
            seq = int(st["stop_sequence"])
            last[st["trip_id"]] = max(last.get(st["trip_id"], 0), seq)
            if st["stop_id"] == stop_id:
                hits.append((st["trip_id"], seq, st["departure_time"].zfill(8)))
    return sum(1 for trip, seq, t in hits if seq < last[trip] and t0 <= t < t1)


def test_departures_lost_matches_a_plain_csv_count():
    from app.m1_disruption import analysis

    closure = {**_drawn("along"), "id": "t_csv"}
    a = analysis.analyze_closure(closure)
    row = next(s for s in a.stops if (s.stopId, s.routeId, s.directionId) == ("59", "R_TV_2", 0))
    expected = _csv_count("59", "R_TV_2", 0, date(2026, 11, 8), "10:00:00", "18:00:00")
    assert expected > 0
    assert row.departuresLost == expected


def test_api_flow_decisions_impact_and_conflicts(client, isolated_state):
    body = {"title": {"ro": "Test 16 Decembrie"}, "kind": "drawn", "geometry": _segment_16dec(),
            "bufferMeters": 30, "direction": "along", "window": WINDOW}
    r = client.post("/api/closures", json=body)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["status"] == "draft"
    assert client.get(f"/api/closures/{cid}/analysis").json()["error"]["code"] == "NOT_ANALYZED"
    assert client.get(f"/api/closures/{cid}/impact").status_code == 404

    a = client.post(f"/api/closures/{cid}/analyze").json()
    assert client.get(f"/api/closures/{cid}").json()["status"] == "analyzed"
    assert client.get(f"/api/closures/{cid}/analysis").json() == a
    assert a["unsureCount"] == sum(1 for s in a["stops"] if s["state"] == "unsure")
    for s in a["stops"]:
        ns = s["nearestServed"]
        assert ns is not None and ns["distanceMeters"] <= 1500 * 1.3

    imp1 = client.get(f"/api/closures/{cid}/impact").json()
    lost = [s for s in a["stops"] if s["state"] == "affected"]
    assert imp1["totals"]["stopRoutePairsLost"] == len(lost)  # unsure rows do not count yet
    assert imp1["totals"]["departuresLost"] == sum(s["departuresLost"] for s in lost)
    assert sum(z["departuresLost"] for z in imp1["byZone"]) == imp1["totals"]["departuresLost"]
    assert sum(z["stopsSuspended"] for z in imp1["byZone"]) == imp1["totals"]["stopsSuspended"]
    assert imp1["totals"]["residentsLosingStop"] is not None
    assert any(p["note"] == "model GHSL 2020, 100 m (nu recensământ)" for p in imp1["provenance"])

    # untick an affected row (an override) and tick an unsure one
    unsure = next(s for s in a["stops"] if s["state"] == "unsure")
    dec = [{"stopId": "63", "routeId": "R_TV_1", "directionId": 0, "confirmed": False},
           {"stopId": unsure["stopId"], "routeId": unsure["routeId"], "directionId": unsure["directionId"],
            "confirmed": True}]
    a2 = client.patch(f"/api/closures/{cid}/stops", json={"decisions": dec}).json()
    row = next(s for s in a2["stops"] if (s["stopId"], s["routeId"]) == ("63", "R_TV_1"))
    assert row["confirmed"] is False
    assert a2["unsureCount"] == a["unsureCount"] - 1
    from app.m1_disruption import analysis

    log = analysis.overrides(cid)
    assert [(e["stopId"], e["routeId"]) for e in log] == [("63", "R_TV_1")]
    imp2 = client.get(f"/api/closures/{cid}/impact").json()
    assert imp2["totals"]["stopRoutePairsLost"] == len(lost)  # one out, one in
    assert imp2["totals"]["departuresLost"] == (imp1["totals"]["departuresLost"] - row["departuresLost"]
                                                + unsure["departuresLost"])
    bad = client.patch(f"/api/closures/{cid}/stops",
                       json={"decisions": [{"stopId": "1", "routeId": "R_TV_4", "directionId": 0, "confirmed": True}]})
    assert bad.status_code == 422

    # a second closure on the same stops at the same time conflicts on stops and corridor
    r2 = client.post("/api/closures", json={**body, "direction": "both"}).json()
    client.post(f"/api/closures/{r2['id']}/analyze")
    kinds = {c["kind"] for c in client.get(f"/api/closures/{cid}/conflicts").json()}
    assert kinds == {"same_stops", "same_corridor"}
    later = client.post("/api/closures", json={**body, "window": {"start": "2026-11-09T10:00:00+02:00",
                                                                 "end": "2026-11-09T18:00:00+02:00"}}).json()
    assert all(c["otherClosureId"] != later["id"] for c in client.get(f"/api/closures/{cid}/conflicts").json())


def test_input_by_line_without_geometry(client, isolated_state):
    body = {"title": {"ro": "Linia 4, Catedrală – Bălcescu"}, "kind": "drawn", "geometry": None, "window": WINDOW,
            "routeActions": [{"routeId": "R_TV_4", "directionId": 0, "action": "suspended",
                              "fromStopId": "86", "toStopId": "55"}]}
    r = client.post("/api/closures", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["geometry"]["type"] == "LineString"
    a = client.post(f"/api/closures/{r.json()['id']}/analyze").json()
    assert [s["stopId"] for s in a["stops"]] == ["86", "61", "57", "55"]
    assert client.post("/api/closures", json={**body, "routeActions": None}).status_code == 422


def test_whole_line_impact_counts_departures_once():
    """Line 4 suspended all day: departures lost = every line 4 departure in the window."""
    from app.m1_disruption import impact

    closure = {"id": "t_l4", "title": {"ro": "t"}, "kind": "notice", "geometry": None, "window": WINDOW,
               "routeActions": [{"routeId": "R_TV_4", "directionId": None, "action": "suspended"}]}
    from app.m1_disruption import analysis

    a = analysis.analyze_closure(closure)
    imp = impact.build_impact(closure, [s.model_dump() for s in a.stops])
    from app.common.timeutil import parse_iso

    direct = gtfs.count_departures(parse_iso(WINDOW["start"]), parse_iso(WINDOW["end"]), route_ids=["R_TV_4"])
    assert imp.totals.departuresLost == direct
    assert imp.totals.stopRoutePairsLost == 46
    # lines 2 and 7 still serve most line 4 stops, so few stops lose all service
    assert 0 < imp.totals.stopsSuspended < 46


HISTORY_429 = DATA_DIR / "gtfs-history" / "smtt-4.29_mdb-2868-202610240049.zip"


@pytest.mark.skipif(not HISTORY_429.is_file(), reason="no GTFS 4.29 in gtfs-history")
def test_mocioni_counts_on_the_timetable_before_the_works():
    """SPEC §5.3: 4.30 (from 2 Nov) already runs the diversion, so a closure from 2 Nov counts on 4.29."""
    from app.m1_disruption import analysis, impact

    assert impact.timetable_for("2026-11-02T00:00:00+02:00").version == "4.29"
    assert not impact.timetable_for(WINDOW["start"]).history  # 8 Nov: the current feed (4.31 from 5 Nov)
    window = {"start": "2026-11-02T00:00:00+02:00", "end": "2026-11-10T00:00:00+02:00"}
    closure = {"id": "t_moc", "title": {"ro": "t"}, "kind": "notice", "geometry": None, "window": window,
               "routeActions": [{"routeId": "R_AB_M36", "directionId": None, "action": "rerouted",
                                 "suspendedStopIds": ["352", "353", "354", "356", "357"]}]}
    a = analysis.analyze_closure(closure)
    assert a.feedVersion == "4.29"
    got = {(s.stopId, s.directionId): s.departuresLost for s in a.stops}
    assert set(got) == {("356", 0), ("357", 0), ("352", 1), ("353", 1), ("356", 1)}
    expected = sum(_csv_count("356", "R_AB_M36", 0, date(2026, 11, d), "00:00:00", "99:00:00", HISTORY_429)
                   for d in range(2, 10))
    assert expected > 0 and got[("356", 0)] == expected
