"""Audio version of the stop alert (SPEC §6.1 item 15): text, hash, budget, cache, endpoint.

ElevenLabs is never called here: requests go to an httpx.MockTransport.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.common import state
from app.m1_disruption import audio
from app.models.v1 import Alert

HERO = audio.HERO_CLOSURE_ID
FAKE_MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb" * 64


def _alert(stop_id: str, stop_name: str = "Catedrala Mitropolitană", tail: str | None = None) -> Alert:
    tail = " Stația rămâne deservită de linia șapte." if tail is None else tail
    return Alert.model_validate({
        "id": f"al_x_stop_{stop_id}", "closureId": HERO,
        "activePeriod": [{"start": "2026-11-08T10:00:00+02:00", "end": "2026-11-08T18:00:00+02:00"}],
        "cause": "MAINTENANCE", "effect": "DETOUR",
        "informedEntity": [{"routeId": "R_TV_4", "stopId": stop_id, "directionId": 1}],
        "headerText": {"ro": "h", "en": "h"}, "descriptionText": {"ro": "d", "en": "d"},
        "url": f"https://example.invalid/a/{HERO}?stop={stop_id}",
        "ttsHeaderText": {"ro": f"Atenție. Stația {stop_name} nu este deservită de linia patru.",
                          "en": "Attention."},
        "ttsDescriptionText": {"ro": "Pe opt noiembrie, între ora zece și ora optsprezece, lucrări." + tail,
                               "en": "x"},
    })


def _route_alert() -> dict:
    a = _alert("0").model_dump(mode="json")
    a["id"] = "al_x_route_R_TV_4"
    a["informedEntity"] = [{"routeId": "R_TV_4", "stopId": None, "directionId": None}]
    return a


CLOSURE = {"id": HERO, "status": "published", "start": "2026-11-08T10:00:00+02:00",
           "end": "2026-11-08T18:00:00+02:00"}


def _store(alerts: list[Alert]) -> None:
    state.write("closures", HERO, CLOSURE)
    state.write("published", HERO, {"closureId": HERO, "alerts": [_route_alert()] +
                                     [a.model_dump(mode="json") for a in alerts],
                                     "feedUrl": "x", "posters": [], "publishedAt": "2026-11-08T12:00:00+02:00"})


class FakeEleven:
    def __init__(self, count: int = 0, limit: int = 10_000):
        self.count, self.limit, self.tts_calls, self.texts = count, limit, 0, []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers.get("xi-api-key") == "test-key"
        if request.url.path == "/v1/user/subscription":
            return httpx.Response(200, json={"character_count": self.count, "character_limit": self.limit})
        if request.url.path.startswith("/v1/text-to-speech/"):
            body = json.loads(request.content)
            assert body["model_id"] == audio.MODEL_ID
            self.tts_calls += 1
            self.texts.append(body["text"])
            return httpx.Response(200, content=FAKE_MP3, headers={"Content-Type": "audio/mpeg"})
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)


# --- text and hash -------------------------------------------------------------------


def test_short_text_has_header_window_and_what_to_do():
    text = audio.short_text(_alert("85"), CLOSURE)
    assert text == ("Atenție. Stația Catedrala Mitropolitană nu este deservită de linia patru. "
                    "Pe opt noiembrie, între ora zece și ora optsprezece. "
                    "Stația rămâne deservită de linia șapte.")
    assert len(text) <= audio.MAX_CHARS
    assert not any(ch.isdigit() for ch in text)


def test_short_text_shortens_the_nearest_stop_sentence():
    tail = " Cea mai apropiată stație deservită este Piața Maria, la o sută douăzeci de metri de mers pe jos."
    text = audio.short_text(_alert("1", "Mecatim", tail), CLOSURE)
    assert text.endswith("Cea mai apropiată stație deservită: Piața Maria, la o sută douăzeci de metri.")


def test_short_text_drops_parts_to_stay_under_the_limit():
    long_name = "Piața Sfânta Maria, șaisprezece Decembrie o mie nouă sute optzeci și nouă"
    text = audio.short_text(_alert("61", long_name), CLOSURE)
    assert len(text) <= audio.MAX_CHARS
    assert "rămâne deservită" in text  # what to do beats the window
    too_long = audio.short_text(_alert("61", "x" * 300), CLOSURE)
    assert too_long is None


def test_a_long_header_never_drops_the_audio():
    # Mocioni stop 356 after R1: six lines, 246 characters: spoken whole
    name = "Piața A. Mocioni, Sinaia, șaisprezece Decembrie o mie nouă sute optzeci și nouă"
    six = ("M treizeci și doi, M treizeci și șase, M treizeci și șapte, M treizeci și opt, "
           "M patruzeci și șase și M cincizeci și unu")
    alert = _alert("356", name)
    alert.ttsHeaderText.ro = f"Atenție. Stația {name} nu este deservită de liniile {six}."
    assert len(alert.ttsHeaderText.ro) == 246
    assert audio.short_text(alert, CLOSURE) == alert.ttsHeaderText.ro
    # longer still: the street qualifier goes first, then the lines are counted, never None
    many = ", ".join([six] * 2)
    alert.ttsHeaderText.ro = f"Atenție. Stația {name} nu este deservită de liniile {six}, {six}."
    text = audio.short_text(alert, CLOSURE)
    assert text.startswith("Atenție. Stația Piața A. Mocioni nu este deservită de liniile M treizeci")
    assert len(text) <= audio.MAX_HEADER_CHARS
    alert.ttsHeaderText.ro = f"Atenție. Stația {name} nu este deservită de liniile {many}, {many}."
    alert.informedEntity = [alert.informedEntity[0].model_copy(update={"routeId": f"R_AB_M{i}"}) for i in range(6)]
    text = audio.short_text(alert, CLOSURE)
    assert text == "Atenție. Stația Piața A. Mocioni nu este deservită de șase linii; liniile sunt pe afiș."


def test_short_text_keeps_a_long_header_alone():
    # Mocioni stop 356: the stop name and four lines make a 206-character header
    name = "Piața A. Mocioni, Sinaia, șaisprezece Decembrie o mie nouă sute optzeci și nouă"
    alert = _alert("356", name)
    alert.ttsHeaderText.ro = (f"Atenție. Stația {name} nu este deservită de liniile M treizeci și doi, "
                              "M treizeci și șase, M treizeci și șapte și M cincizeci și unu.")
    assert audio.MAX_CHARS < len(alert.ttsHeaderText.ro) <= audio.MAX_HEADER_CHARS
    assert audio.short_text(alert, CLOSURE) == alert.ttsHeaderText.ro


def test_hash_covers_voice_model_and_text():
    h = audio.text_hash("a", "v1", "m1")
    assert h != audio.text_hash("a", "v2", "m1")
    assert h != audio.text_hash("a", "v1", "m2")
    assert h != audio.text_hash("b", "v1", "m1")
    assert h == audio.text_hash("a", "v1", "m1")


# --- generation, budget, cache ---------------------------------------------------------


def test_generate_makes_one_mp3_per_distinct_text_and_never_twice(isolated_state, key):
    # 85 and 86 have the same name, so the same text: one MP3 serves both.
    _store([_alert("85"), _alert("86"), _alert("87", "Mendeleev")])
    fake = FakeEleven()
    s = audio.generate(HERO, client=fake.client())
    assert s["skipped"] is None and fake.tts_calls == 2 and s["planned"] == 2
    assert s["charsSpent"] == sum(len(t) for t in fake.texts)
    for stop in ("85", "86", "87"):
        assert audio.audio_file(HERO, stop).read_bytes() == FAKE_MP3
    again = audio.generate(HERO, client=fake.client())
    assert fake.tts_calls == 2 and again["planned"] == 0 and again["cached"] == 3
    runs = (isolated_state.cache_dir / "audio" / "runs.jsonl").read_text(encoding="utf-8")
    assert "test-key" not in runs


def test_budget_refuses_the_whole_batch(isolated_state, key):
    _store([_alert("85"), _alert("87", "Mendeleev")])
    fake = FakeEleven(count=audio.CHAR_CEILING - 200)
    with pytest.raises(audio.BudgetRefused):
        audio.generate(HERO, client=fake.client())
    assert fake.tts_calls == 0
    assert audio.audio_file(HERO, "85") is None


def test_budget_counts_our_own_spend_when_the_account_lags(isolated_state, key, monkeypatch):
    _store([_alert("85")])
    monkeypatch.setattr(audio, "spent_locally", lambda: audio.CHAR_CEILING - 10)
    fake = FakeEleven(count=0)  # the account has not caught up yet
    with pytest.raises(audio.BudgetRefused):
        audio.generate(HERO, client=fake.client())
    assert fake.tts_calls == 0


def test_limit_makes_only_one_stop(isolated_state, key):
    _store([_alert("85"), _alert("87", "Mendeleev"), _alert("88", "Amforei")])
    fake = FakeEleven()
    s = audio.generate(HERO, limit=1, client=fake.client())
    assert fake.tts_calls == 1 and len(s["made"]) == 1


def test_no_key_or_other_closure_makes_nothing(isolated_state, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    _store([_alert("85")])
    assert audio.generate(HERO)["skipped"] == "no ELEVENLABS_API_KEY"
    assert audio.generate("cl_20261107_e3")["skipped"] == "no audio for this closure"
    assert audio.start_after_publish("cl_20261107_e3") is None


# --- endpoint --------------------------------------------------------------------------


def test_endpoint_serves_the_mp3_and_404s_otherwise(isolated_state, key, client):
    _store([_alert("85"), _alert("87", "Mendeleev")])
    fake = FakeEleven()
    audio.generate(HERO, limit=1, client=fake.client())  # only stop 85
    r = client.get(f"/api/closures/{HERO}/audio/85.mp3")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert r.content == FAKE_MP3
    assert client.head(f"/api/closures/{HERO}/audio/85.mp3").status_code == 200
    for path in (f"/api/closures/{HERO}/audio/87.mp3",          # not made
                 f"/api/closures/{HERO}/audio/999.mp3",         # not affected
                 "/api/closures/cl_20261107_e3/audio/85.mp3"):  # no audio for E3
        r = client.get(path)
        assert r.status_code == 404, path
        assert r.json()["error"]["code"] == "NO_AUDIO"


def test_publish_hook_never_breaks_publish(monkeypatch):
    from app.m1_disruption import publish

    def boom(_cid):
        raise RuntimeError("x")

    monkeypatch.setattr(audio, "start_after_publish", boom)
    publish.start_audio(HERO)  # logs, does not raise
