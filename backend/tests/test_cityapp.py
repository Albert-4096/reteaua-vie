"""S1 stop status and R3 tools.json on the prepared cases."""

from __future__ import annotations

import pytest

from app.cityapp import status
from app.cityapp.models import StopLine
from app.models.base import I18n
from tests.conftest import needs_data

AT = "2026-11-08T12:00:00+02:00"


def _line(short: str, stops: str) -> StopLine:
    return StopLine(routeId="R_" + short, shortName=short, directionId=0, headsign=None, stops=stops,
                    reason=None, nextDepartureAt=None)


def test_sentence_singular_and_plural():
    one = status.build_sentence("Bucla", "suspended", [_line("E3", "no")], None, None)
    assert "linia E3 nu oprește" in one.ro and "line E3 does not stop" in one.en
    two = status.build_sentence("X", "partial", [_line("1", "no"), _line("2", "no"), _line("3", "yes")], None, None)
    assert "liniile 1, 2 nu opresc" in two.ro and "Opresc: 3." in two.ro


def test_sentence_names_nearest_only_when_walk_is_positive():
    near = {"stopId": "9", "name": "Banatul", "distanceMeters": 330.0}
    assert "Banatul, la aproximativ 330 m" in status.build_sentence("X", "suspended", [_line("E3", "no")], near, None).ro
    near["distanceMeters"] = 0
    assert "Banatul" not in status.build_sentence("X", "suspended", [_line("E3", "no")], near, None).ro


def test_o2_hook_is_pending_not_faked():
    from datetime import datetime

    from app.config import TZ
    assert status.live_gap_hook("R_TV_4", datetime(2026, 11, 8, 12, tzinfo=TZ)) is None
    assert status.live_feed_check().status in ("pending", "ok")


@needs_data
def test_mocioni_stop_lists_lines_that_do_not_stop(client):
    r = client.get("/api/stops/356/status", params={"at": AT})
    assert r.status_code == 200
    d = r.json()
    no = {ln["shortName"] for ln in d["lines"] if ln["stops"] == "no"}
    yes = {ln["shortName"] for ln in d["lines"] if ln["stops"] == "yes"}
    assert {"M32", "M36"} <= no and yes
    assert d["state"] == "partial"
    reason = next(ln for ln in d["lines"] if ln["stops"] == "no")["reason"]
    assert reason["closureId"] == "cl_20261102_mocioni" and reason["noticeUrl"].startswith("https://stpt.ro/")
    assert d["sentence"]["ro"] and d["sentence"]["en"] and d["provenance"]
    assert d["liveFeed"]["status"] in ("pending", "ok")


@needs_data
def test_e3_stop_suspended_with_nearest(client):
    d = client.get("/api/stops/335/status", params={"at": "2026-11-09T09:00:00+02:00"}).json()
    assert d["state"] == "suspended" and d["nearestServed"]["stopId"] == "334"
    assert "330 m" in d["sentence"]["ro"]


@needs_data
def test_normal_stop_and_unknown_stop(client):
    d = client.get("/api/stops/1/status", params={"at": AT}).json()
    assert d["state"] == "normal" and all(ln["stops"] == "yes" for ln in d["lines"])
    assert client.get("/api/stops/999999/status").status_code == 404
    assert client.get("/api/stops/1/status", params={"at": "tomorrow"}).status_code == 422


@needs_data
def test_stop_search(client):
    names = [h["name"] for h in client.get("/api/stops/search", params={"q": "MOCIONI"}).json()]
    assert names and all("Mocioni" in n for n in names)
    near = client.get("/api/stops/search", params={"lat": 45.7454, "lon": 21.215, "radius": 150}).json()
    assert near[0]["stopId"] == "356" and near[0]["distanceMeters"] < 10
    assert client.get("/api/stops/search").status_code == 422


@needs_data
def test_tools_json_every_live_function_answers(client):
    d = client.get("/api/tools.json").json()
    assert d["readOnly"] and len(d["tools"]) == 4
    by = {t["name"]: t for t in d["tools"]}
    assert by["get_stop_status"]["live"] and by["get_notices"]["live"]
    for t in d["tools"]:
        assert t["http"]["method"] == "GET" and t["description"] and t["parameters"]["type"] == "object"
        if not t["live"]:
            assert t["note"]
    # the live GETs with sample arguments (the route is a job: 200 or 202)
    assert client.get("/api/stops/356/status").status_code == 200
    assert client.get("/api/feed/notices.json").status_code == 200
    assert by["plan_route"]["live"]
