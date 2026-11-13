"""M1 outputs: GTFS-RT alerts (round-trip, validator), publish (409 path), the stop poster.

The Analysis used here is built inside the tests from real ids of line 4
(R_TV_4) around Piața Sfânta Maria, the hero case's area. It exists only in a
temp state dir; it is never served as data.
"""

from __future__ import annotations

import io
from datetime import datetime

import pytest
from conftest import needs_data

from app import config
from app.common import gtfs
from app.common.city import load_network
from app.common.geo import haversine_m
from app.config import TZ
from app.m1_disruption import alerts as al
from app.models.v1 import Analysis

CLOSURE_ID = "cl_test_outputs_l4"
START = "2026-11-08T10:00:00+02:00"
END = "2026-11-08T18:00:00+02:00"
STOP_MARIA = "61"          # Piața Sfânta Maria (16 Decembrie 1989), line 4 direction 0


# --- pure text helpers --------------------------------------------------------------


def test_numbers_as_words():
    assert al.ro_words(1989) == "o mie nouă sute optzeci și nouă"
    assert al.ro_words(2026) == "două mii douăzeci și șase"
    assert al.ro_count(350, "metru", "metri") == "trei sute cincizeci de metri"
    assert al.ro_count(115, "metru", "metri") == "o sută cincisprezece metri"
    assert al.en_words(350) == "three hundred and fifty"
    assert al.en_ordinal(8) == "eighth" and al.en_ordinal(21) == "twenty-first"


def test_tts_has_no_digits_or_abbreviations():
    spoken = al.speak_ro("Bd. 16 Decembrie 1989, Str. Ardealului Nr. 12")
    assert spoken == "Bulevardul șaisprezece Decembrie o mie nouă sute optzeci și nouă, Strada Ardealului numărul doisprezece"
    assert al.speak_en("16 Decembrie 1989 Blvd") == "sixteen Decembrie nineteen eighty-nine Boulevard"
    s, e = datetime(2026, 11, 8, 10, tzinfo=TZ), datetime(2026, 11, 8, 18, tzinfo=TZ)
    assert al.window_tts(s, e, "ro") == "Pe opt noiembrie, între ora zece și ora optsprezece"
    assert al.window_tts(s, e, "en") == "On the eighth of November, from ten in the morning until six in the evening"
    # an end at 00:00 reads as 24:00 of the day before, as STPT writes it
    e3 = datetime(2026, 11, 13, 0, tzinfo=TZ)
    assert al.window_text(datetime(2026, 11, 7, 4, tzinfo=TZ), e3, "ro") == \
        "7 noiembrie 2026, 04:00 – 12 noiembrie 2026, 24:00"


def test_lines_phrase():
    assert al.lines_phrase(["7", "4"], "ro") == "liniile 4 și 7"
    assert al.lines_phrase(["2", "7", "4"], "en") == "lines 2, 4 and 7"
    assert al.lines_phrase(["E3"], "ro", spoken=True) == "linia E trei"


# --- a line 4 analysis built in the test ---------------------------------------------


def _nearest_other_stop(stop_id: str, avoid_route: str) -> dict:
    """Closest stop not on `avoid_route` (straight line x 1.3, like m1-core's fallback)."""
    n = load_network()
    here = n.stop_by_id[stop_id]["location"]
    best = None
    for s in n.stops:
        if avoid_route in (s.get("routeIds") or []) or not s.get("routeIds"):
            continue
        d = haversine_m(here[0], here[1], s["location"][0], s["location"][1])
        if best is None or d < best[0]:
            best = (d, s)
    d, s = best
    return {"stopId": s["id"], "name": s["name"], "location": s["location"],
            "distanceMeters": round(d * 1.3), "routeIds": sorted(s["routeIds"])}


def _row(stop_id: str, direction: int, state: str = "affected", confirmed=None) -> dict:
    n = load_network()
    s = n.stop_by_id[stop_id]
    start, end = datetime.fromisoformat(START), datetime.fromisoformat(END)
    return {
        "stopId": stop_id, "name": s["name"], "location": s["location"], "zoneSlug": None,
        "routeId": "R_TV_4", "routeShortName": "4", "directionId": direction, "headsign": None,
        "state": state, "confidence": 0.9 if state == "affected" else 0.6,
        "reasons": ["NAMED_IN_NOTICE"], "confirmed": confirmed,
        "departuresLost": gtfs.count_departures(start, end, stop_ids=[stop_id], route_ids=["R_TV_4"],
                                                direction_id=direction),
        "nearestServed": _nearest_other_stop(stop_id, "R_TV_4"),
    }


def _closure() -> dict:
    return {
        "id": CLOSURE_ID, "status": "analyzed", "createdAt": "2026-11-08T09:00:00+02:00",
        "title": {"ro": "Lucrări la linia de tramvai, Bd. 16 Decembrie 1989",
                  "en": "Tram track works, 16 Decembrie 1989 Blvd"},
        "kind": "notice", "geometry": None, "bufferMeters": 30, "direction": "both",
        "window": {"start": START, "end": END}, "routeIds": ["R_TV_4"],
        "sourceText": None, "sourceUrl": None,
        "routeActions": [{"routeId": "R_TV_4", "directionId": None, "action": "suspended",
                          "fromStopId": None, "toStopId": None, "keepStopIds": None,
                          "suspendedStopIds": None, "stopNames": None}],
        "temporaryRoutes": [{"shortName": "4b", "mode": "bus", "stopIds": None, "geometry": None,
                             "streets": ["Piața Iuliu Maniu", "Bd. 16 Decembrie 1989"]}],
    }


def _analysis(unsure_decision="missing") -> dict:
    order0 = gtfs.stop_order("R_TV_4", 0)
    i = order0.index(STOP_MARIA)
    rows = [_row(s, 0) for s in order0[i - 1:i + 2]]
    rows += [_row(s, 1) for s in ("58", "60")]
    unsure = _row(order0[i + 2], 0, state="unsure",
                  confirmed=None if unsure_decision == "missing" else unsure_decision)
    rows.append(unsure)
    a = Analysis.model_validate({
        "closureId": CLOSURE_ID, "feedVersion": gtfs.feed().version or "?", "stops": rows,
        "routes": [{"routeId": "R_TV_4", "shortName": "4", "type": 0, "directionIds": [0, 1],
                    "stopsAffected": len(rows)}],
        "unsureCount": 1, "provenance": [gtfs.feed().provenance.model_dump()],
    })
    return a.model_dump(mode="json")


@pytest.fixture
def outputs_state(tmp_path, monkeypatch):
    """Temp state + cache dirs; the validator jar is linked in from the real $DATA_DIR/tools."""
    real = config.get_settings()
    fake = config.Settings(env_file=None, data_dir=tmp_path, live_dir=real.live_dir,
                           demo_now=real.demo_now, data_freeze=False,
                           public_base_url=real.public_base_url)
    monkeypatch.setattr(config, "get_settings", lambda: fake)
    import app.common.state as state_mod

    monkeypatch.setattr(state_mod, "get_settings", lambda: fake)
    config.ensure_dirs(fake)
    if (real.data_dir / "tools").is_dir():
        (tmp_path / "tools").symlink_to(real.data_dir / "tools")
    yield fake


def _store(closure: dict, analysis: dict) -> None:
    from app.common import state

    state.write("closures", closure["id"], closure)
    state.write("closures", closure["id"], analysis, state.PART_ANALYSIS)


# --- alerts and the protobuf round-trip ----------------------------------------------


@needs_data
def test_alerts_for_line_4(outputs_state):
    alerts = al.build_alerts(_closure(), _analysis(unsure_decision=True))
    ids = [a.id for a in alerts]
    assert ids[0] == "al_test_outputs_l4_route_R_TV_4"           # whole-line suspended: route level
    route = alerts[0]
    assert route.effect == "NO_SERVICE" and route.informedEntity[0].stopId is None
    assert route.headerText.ro == "Linia 4 nu circulă"
    assert "4b" in route.descriptionText.ro

    maria = next(a for a in alerts if a.id.endswith(f"_stop_{STOP_MARIA}"))
    assert maria.cause == "MAINTENANCE"
    assert maria.url == f"{config.get_settings().public_base_url}/a/{CLOSURE_ID}?stop={STOP_MARIA}"
    assert [(e.routeId, e.stopId, e.directionId) for e in maria.informedEntity] == [("R_TV_4", STOP_MARIA, 0)]
    assert maria.headerText.ro.startswith("Stația Piața Sfânta Maria")
    assert maria.descriptionText.ro.startswith("8 noiembrie 2026, 10:00–18:00: Lucrări")
    # the GTFS says which other lines still stop here in the window -> DETOUR, else NO_SERVICE
    left = gtfs.departures(datetime.fromisoformat(START), datetime.fromisoformat(END), stop_ids=[STOP_MARIA])
    others = set(left[left["route_id"] != "R_TV_4"]["route_id"])
    assert maria.effect == ("DETOUR" if others else "NO_SERVICE")
    for a in alerts:
        for text in (a.ttsHeaderText.ro, a.ttsDescriptionText.ro, a.ttsHeaderText.en, a.ttsDescriptionText.en):
            assert not any(ch.isdigit() for ch in text), text
            assert "Bd." not in text and "Str." not in text


@needs_data
def test_protobuf_round_trip(outputs_state):
    alerts = al.build_alerts(_closure(), _analysis(unsure_decision=True))
    stamp = datetime(2026, 11, 8, 12, tzinfo=TZ)
    data = al.feed_message(alerts, stamp).SerializeToString()

    from google.transit import gtfs_realtime_pb2 as rt

    msg = rt.FeedMessage()
    msg.ParseFromString(data)
    assert msg.header.gtfs_realtime_version == "2.0"
    assert msg.header.incrementality == rt.FeedHeader.FULL_DATASET
    assert msg.header.timestamp == int(stamp.timestamp())
    assert msg.SerializeToString() == data
    back = al.alert_dicts_from_feed(data)
    expected = [a.model_dump(mode="json", exclude={"closureId"}) for a in alerts]
    assert back == expected


# --- publish: the 409 path, then a real publish -----------------------------------------


@needs_data
def test_publish_refused_while_unsure_row_undecided(outputs_state, client):
    _store(_closure(), _analysis(unsure_decision="missing"))
    r = client.post(f"/api/closures/{CLOSURE_ID}/publish")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "UNCONFIRMED"
    assert client.get("/api/feed/alerts.json").json() == []


@needs_data
def test_publish_then_feeds_and_validator(outputs_state, client):
    _store(_closure(), _analysis(unsure_decision=False))
    r = client.post(f"/api/closures/{CLOSURE_ID}/publish")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["closureId"] == CLOSURE_ID
    rows = _analysis()["stops"]
    expected = {r["stopId"] for r in rows if r["state"] == "affected"}
    assert {p["stopId"] for p in body["posters"]} == expected            # the unsure row was unticked
    assert rows[-1]["stopId"] not in expected

    from app.common import state

    assert state.read("closures", CLOSURE_ID)["status"] == "published"

    feed_json = client.get("/api/feed/alerts.json").json()
    assert [a["id"] for a in feed_json] == [a["id"] for a in body["alerts"]]
    pb = client.get("/api/feed/alerts.pb")
    assert pb.headers["content-type"] == "application/x-protobuf"
    assert [a["id"] for a in al.alert_dicts_from_feed(pb.content)] == [a["id"] for a in body["alerts"]]

    v = client.get(f"/api/closures/{CLOSURE_ID}/validation").json()
    assert v["closureId"] == CLOSURE_ID and v["feed"]["entities"] == len(body["alerts"])
    assert v["passed"] is True, v["rules"]
    if (outputs_state.data_dir / "tools").exists():
        assert v["method"] == "validator", v["fallbackReason"]


@needs_data
def test_feed_drops_alerts_after_their_window(outputs_state, client):
    from app.m1_disruption import publish

    _store(_closure(), _analysis(unsure_decision=True))
    publish.publish(CLOSURE_ID)
    assert publish.published_alerts(datetime(2026, 11, 8, 17, 59, tzinfo=TZ))
    assert publish.published_alerts(datetime(2026, 11, 8, 18, 0, tzinfo=TZ)) == []


# --- poster ------------------------------------------------------------------------------


@needs_data
def test_poster_pdf_has_the_stop_name(outputs_state, client):
    from pypdf import PdfReader

    _store(_closure(), _analysis(unsure_decision=True))
    r = client.get(f"/api/closures/{CLOSURE_ID}/poster.pdf", params={"stopId": STOP_MARIA})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    pdf = PdfReader(io.BytesIO(r.content))
    assert len(pdf.pages) == 1
    box = pdf.pages[0].mediabox
    assert (round(float(box.width)), round(float(box.height))) == (595, 842)    # A4 portrait, points
    text = pdf.pages[0].extract_text()
    flat = " ".join(text.split())
    assert "Piața Sfânta Maria" in flat
    assert "Scanați pentru varianta audio" in flat
    assert f"/a/{CLOSURE_ID}?stop={STOP_MARIA}" in flat.replace(" ", "")
    for ch in "ăâîșț":
        assert ch in flat, ch
    names = {str(f.get_object()["/BaseFont"]) for f in pdf.pages[0]["/Resources"]["/Font"].values()}
    assert any("Noto-Sans" in n or "NotoSans" in n for n in names), names

    missing = client.get(f"/api/closures/{CLOSURE_ID}/poster.pdf", params={"stopId": "999999"})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "STOP_NOT_AFFECTED"
