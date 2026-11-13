"""Audio version of a stop alert (SPEC §6.1 item 15).

At publish of the hero case, one short Romanian MP3 per affected stop is made with
ElevenLabs (multilingual v2) and cached under $DATA_DIR/cache/audio/<sha256>.mp3,
where the hash covers (voice, model, text). An existing hash is never generated again.

Budget (free tier, 10,000 characters a month): before a batch we read the account's
character_count and refuse the whole batch if it would push the count above
CHAR_CEILING. Texts are at most MAX_CHARS characters. Only HERO_CLOSURE_ID gets MP3s;
every other closure answers 404 and the QR page reads `ttsDescriptionText` with Web
Speech (ro-RO).

The text is derived from the stored alert of the stop, so the GET handler and the
generator agree on the hash without an index file. The API key is never logged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx

from app import config
from app.common import state
from app.common.timeutil import iso, parse_iso
from app.m1_disruption.alerts import is_open_end, window_tts
from app.models.v1 import Alert

log = logging.getLogger("reteaua_vie.audio")

HERO_CLOSURE_ID = "cl_20261108_16dec"
API = "https://api.elevenlabs.io/v1"
MODEL_ID = "eleven_multilingual_v2"
# Premade ElevenLabs voice "Daniel - Steady Broadcaster" (multilingual v2). Override with
# ELEVENLABS_VOICE_ID (SPEC §3.5).
DEFAULT_VOICE_ID = "onwK4e9ZLuTAKqWW03F9"
DEFAULT_VOICE_NAME = "Daniel"
OUTPUT_FORMAT = "mp3_44100_128"
MAX_CHARS = 200
CHAR_CEILING = 8000  # never let the month's character_count go above this
LABEL = {"ro": "Voce generată automat (AI), ElevenLabs", "en": "AI-generated voice, ElevenLabs"}

_batch_lock = threading.Lock()


class BudgetRefused(RuntimeError):
    """The batch would push the month's character count above CHAR_CEILING."""


def voice_id() -> str:
    config.get_settings()  # loads ENV_FILE
    return os.environ.get("ELEVENLABS_VOICE_ID", "").strip() or DEFAULT_VOICE_ID


def audio_dir() -> Path:
    return config.get_settings().cache_dir / "audio"


# --- the short text ------------------------------------------------------------------

_NEAREST = re.compile(r"Cea mai apropiată stație deservită este (?P<name>.+), la (?P<dist>.+?) de mers pe jos\.\s*$")
_STILL = re.compile(r"(?P<still>Stația rămâne deservită de [^.]+\.)\s*$")


def _tail(tts_description: str) -> str:
    """The stop-specific end of the alert's tts description, shortened."""
    m = _NEAREST.search(tts_description)
    if m:
        return f"Cea mai apropiată stație deservită: {m['name']}, la {m['dist']}."
    m = _STILL.search(tts_description)
    return m["still"] if m else ""


def short_text(alert: Alert, closure: dict) -> str | None:
    """A ≤ MAX_CHARS Romanian text for one stop alert, or None if even the header is too long.

    Order of preference: header + window + what to do; header + what to do;
    header + window; header alone.
    """
    if alert.ttsHeaderText is None or not alert.ttsHeaderText.ro:
        return None
    header = alert.ttsHeaderText.ro.strip()
    if not header.endswith("."):
        header += "."
    window = ""
    if alert.activePeriod:
        p = alert.activePeriod[0]
        window = window_tts(parse_iso(p.start), parse_iso(p.end), "ro", is_open_end(closure)) + "."
    desc = alert.ttsDescriptionText.ro if alert.ttsDescriptionText and alert.ttsDescriptionText.ro else ""
    tail = _tail(desc)
    for parts in ((header, window, tail), (header, tail), (header, window), (header,)):
        text = " ".join(p for p in parts if p)
        if len(text) <= MAX_CHARS:
            return text
    return None


def text_hash(text: str, voice: str | None = None, model: str = MODEL_ID) -> str:
    return hashlib.sha256(f"{voice or voice_id()}\n{model}\n{text}".encode("utf-8")).hexdigest()


def mp3_path(digest: str) -> Path:
    return audio_dir() / f"{digest}.mp3"


# --- which stops ---------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    stop_id: str
    text: str
    digest: str


def stop_alerts(published: dict) -> dict[str, Alert]:
    """Per-stop alerts of a stored PublishResult, by stop id (route-level alerts skipped)."""
    out: dict[str, Alert] = {}
    for raw in published.get("alerts") or []:
        alert = Alert.model_validate(raw)
        stops = {e.stopId for e in alert.informedEntity if e.stopId}
        if len(stops) == 1:
            out.setdefault(next(iter(stops)), alert)
    return out


def items_for(closure: dict, published: dict) -> list[Item]:
    voice = voice_id()
    out: list[Item] = []
    for stop_id, alert in stop_alerts(published).items():
        text = short_text(alert, closure)
        if text:
            out.append(Item(stop_id, text, text_hash(text, voice)))
    return out


def audio_file(closure_id: str, stop_id: str) -> Path | None:
    """The cached MP3 for this stop of a published closure, or None."""
    if closure_id != HERO_CLOSURE_ID:
        return None
    try:
        published = state.read("published", closure_id)
        closure = state.read("closures", closure_id)
    except ValueError:
        return None
    if not published or not closure:
        return None
    alert = stop_alerts(published).get(stop_id)
    if alert is None:
        return None
    text = short_text(alert, closure)
    if not text:
        return None
    path = mp3_path(text_hash(text))
    return path if path.is_file() else None


# --- ElevenLabs ----------------------------------------------------------------------


def _headers(key: str) -> dict[str, str]:
    return {"xi-api-key": key, "Accept": "application/json"}


def subscription(key: str, client: httpx.Client) -> tuple[int, int]:
    """(character_count, character_limit) of the account this month."""
    r = client.get(f"{API}/user/subscription", headers=_headers(key))
    r.raise_for_status()
    data = r.json()
    return int(data["character_count"]), int(data["character_limit"])


def synthesize(key: str, client: httpx.Client, text: str, voice: str) -> bytes:
    r = client.post(
        f"{API}/text-to-speech/{voice}",
        params={"output_format": OUTPUT_FORMAT},
        headers={**_headers(key), "Accept": "audio/mpeg"},
        json={"text": text, "model_id": MODEL_ID},
    )
    if r.status_code != 200:
        # The body is ElevenLabs' error JSON; it never contains the key.
        raise RuntimeError(f"ElevenLabs HTTP {r.status_code}: {r.text[:200]}")
    if not r.content.startswith((b"ID3", b"\xff")):
        raise RuntimeError("ElevenLabs answered 200 without MP3 data")
    return r.content


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.chmod(tmp, 0o664)
    os.replace(tmp, path)


def spent_locally() -> int:
    """Characters this app has spent, from runs.jsonl (the account's count lags behind)."""
    path = audio_dir() / "runs.jsonl"
    total = 0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                total += int(json.loads(line).get("charsSpent") or 0)
            except (ValueError, AttributeError):
                continue
    except FileNotFoundError:
        return 0
    return total


def _log_run(entry: dict) -> None:
    path = audio_dir() / "runs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def generate(closure_id: str, limit: int | None = None, client: httpx.Client | None = None) -> dict:
    """Make the missing MP3s of a published closure within the budget.

    `limit` caps how many new MP3s are made (development: one stop). Returns a summary
    that is also appended to $DATA_DIR/cache/audio/runs.jsonl. Raises BudgetRefused when
    the batch would exceed CHAR_CEILING (nothing is generated then).
    """
    if closure_id != HERO_CLOSURE_ID:
        return {"closureId": closure_id, "skipped": "not the hero case"}
    published = state.read("published", closure_id)
    closure = state.read("closures", closure_id)
    if not published or not closure:
        return {"closureId": closure_id, "skipped": "not published"}
    return synthesize_items(closure_id, items_for(closure, published), limit, client)


def synthesize_items(closure_id: str, items: list[Item], limit: int | None = None,
                     client: httpx.Client | None = None) -> dict:
    """Generate the MP3s of `items` that are not cached yet, as one budget-checked batch."""
    summary: dict = {"closureId": closure_id, "at": iso(config.real_now()), "voiceId": voice_id(),
                     "modelId": MODEL_ID, "made": [], "cached": 0, "skipped": None}
    key = config.secret("ELEVENLABS_API_KEY")
    if not key:
        summary["skipped"] = "no ELEVENLABS_API_KEY"
        return summary
    with _batch_lock:
        todo: dict[str, Item] = {}
        for it in items:
            if mp3_path(it.digest).is_file():
                summary["cached"] += 1
            else:
                todo.setdefault(it.digest, it)
        batch = list(todo.values())[:limit] if limit is not None else list(todo.values())
        summary["planned"] = len(batch)
        summary["batchChars"] = sum(len(it.text) for it in batch)
        if not batch:
            _log_run(summary)
            return summary
        own = client is None
        client = client or httpx.Client(timeout=60)
        try:
            api_count, limit_chars = subscription(key, client)
            count = max(api_count, spent_locally())
            ceiling = min(CHAR_CEILING, limit_chars)
            summary["characterCountBefore"] = api_count
            summary["characterCountUsed"] = count
            summary["characterLimit"] = limit_chars
            if count + summary["batchChars"] > ceiling:
                summary["skipped"] = f"budget: {count} + {summary['batchChars']} > {ceiling}"
                _log_run(summary)
                raise BudgetRefused(summary["skipped"])
            spent = 0
            try:
                for it in batch:
                    data = synthesize(key, client, it.text, summary["voiceId"])
                    _write_atomic(mp3_path(it.digest), data)
                    _write_atomic(mp3_path(it.digest).with_suffix(".json"), json.dumps(
                        {"stopId": it.stop_id, "closureId": closure_id, "voiceId": summary["voiceId"],
                         "modelId": MODEL_ID, "text": it.text, "chars": len(it.text), "bytes": len(data)},
                        ensure_ascii=False).encode("utf-8"))
                    spent += len(it.text)
                    summary["made"].append({"stopId": it.stop_id, "chars": len(it.text), "bytes": len(data)})
                    log.info("audio %s stop %s: %d characters", closure_id, it.stop_id, len(it.text))
            finally:
                summary["charsSpent"] = spent
                try:
                    summary["characterCountAfter"] = subscription(key, client)[0]
                except httpx.HTTPError:
                    summary["characterCountAfter"] = None
                _log_run(summary)
        finally:
            if own:
                client.close()
        log.info("audio %s: %d MP3 made, %d characters, %d cached", closure_id,
                 len(summary["made"]), summary["charsSpent"], summary["cached"])
        return summary


# --- the publish hook ------------------------------------------------------------------


def _run(closure_id: str) -> None:
    try:
        generate(closure_id)
    except BudgetRefused as exc:
        log.warning("audio %s refused: %s", closure_id, exc)
    except Exception:  # noqa: BLE001 - audio never breaks publish; the QR page falls back
        log.exception("audio generation failed for %s", closure_id)


def start_after_publish(closure_id: str) -> threading.Thread | None:
    """Called by publish(): make the hero case's MP3s in a background thread."""
    if closure_id != HERO_CLOSURE_ID:
        return None
    job = threading.Thread(target=_run, args=(closure_id,), daemon=True, name=f"audio-{closure_id}")
    job.start()
    return job
