"""Publishing a closure and serving the alert feed (SPEC §6.1 items 7, 11, 12).

POST /api/closures/{id}/publish stores a PublishResult in
$DATA_DIR/state/published/<id>.json and sets the closure's status to
`published`. The feeds (/api/feed/alerts.pb and .json) are built from every
stored PublishResult, keeping the alerts whose window has not ended at "now"
(the demo clock when DEMO_NOW is set).

After each publish the whole feed is validated in a background thread and the
result is stored as published/<id>.validation.json, so the publish answer is
fast and GET /api/closures/{id}/validation returns once the validator is done.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from pydantic import BaseModel

from app import config
from app.common import state
from app.common.errors import ApiError, conflict, not_found
from app.common.timeutil import iso, parse_iso
from app.m1_disruption.alerts import (
    FeedValidation,
    build_alerts,
    feed_message,
    suspended_rows,
    undecided_rows,
    validate_feed,
)
from app.models.v1 import Alert, Poster, PublishResult

log = logging.getLogger("reteaua_vie.publish")

PART_VALIDATION = "validation"


def closure_or_404(closure_id: str) -> dict:
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id!r}.")
    return closure


def load_analysis(closure_id: str) -> dict | None:
    """The last Analysis with the decisions applied, or None if it was never analyzed.

    Uses m1-core's `get_analysis` when that module exists; otherwise the stored
    state part (the same data, by the shared state convention).
    """
    try:
        from app.m1_disruption import analysis as core
    except ModuleNotFoundError as exc:
        if exc.name != "app.m1_disruption.analysis":
            raise
        core = None
    getter = getattr(core, "get_analysis", None)
    if getter is None:
        return state.read("closures", closure_id, state.PART_ANALYSIS)
    try:
        result = getter(closure_id)
    except ApiError as exc:
        if exc.status_code == 404:
            return None
        raise
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json", by_alias=True)
    return result


def analysis_or_409(closure_id: str) -> dict:
    analysis = load_analysis(closure_id)
    if analysis is None:
        raise conflict(f"Closure {closure_id!r} has not been analyzed yet (POST .../analyze first).",
                       "NOT_ANALYZED")
    return analysis


def poster_url(closure_id: str, stop_id: str) -> str:
    base = config.get_settings().public_base_url
    return f"{base}/api/closures/{closure_id}/poster.pdf?stopId={stop_id}"


def feed_url() -> str:
    return f"{config.get_settings().public_base_url}/api/feed/alerts.pb"


def publish(closure_id: str) -> PublishResult:
    closure = closure_or_404(closure_id)
    analysis = analysis_or_409(closure_id)
    undecided = undecided_rows(analysis)
    if undecided:
        sample = ", ".join(f"{r.get('name') or r['stopId']} ({r.get('routeShortName') or r['routeId']})"
                           for r in undecided[:5])
        raise conflict(
            f"{len(undecided)} stații neclare fără decizie / unsure stops without a decision: {sample}"
            + (" …" if len(undecided) > 5 else ""),
            "UNCONFIRMED",
        )
    alerts = build_alerts(closure, analysis)
    if not alerts:
        raise conflict("Nicio stație sau linie suspendată: nu avem ce publica / nothing is suspended, "
                       "nothing to publish.", "NOTHING_TO_PUBLISH")
    stop_ids = list(dict.fromkeys(str(r["stopId"]) for r in suspended_rows(analysis)))
    result = PublishResult(
        closureId=closure_id,
        alerts=alerts,
        feedUrl=feed_url(),
        posters=[Poster(stopId=s, url=poster_url(closure_id, s)) for s in stop_ids],
        publishedAt=iso(config.now()),
    )
    state.write("published", closure_id, result)
    state.delete("published", closure_id, PART_VALIDATION)

    def _set_status(old: dict | None) -> dict:
        return {**(old or closure), "status": "published"}

    state.update("closures", closure_id, _set_status)
    start_validation(closure_id)
    start_audio(closure_id)
    return result


def start_audio(closure_id: str) -> None:
    """The hero case's MP3s (SPEC §6.1 item 15), in the background; never fails a publish."""
    try:
        from app.m1_disruption import audio

        audio.start_after_publish(closure_id)
    except Exception:  # noqa: BLE001 - without audio the QR page uses Web Speech
        log.exception("could not start audio generation for %s", closure_id)


# --- the feed -------------------------------------------------------------------------


def _active(alert: Alert, at: datetime) -> bool:
    if not alert.activePeriod:
        return True
    return any(parse_iso(p.end) > at for p in alert.activePeriod)


def published_alerts(at: datetime | None = None) -> list[Alert]:
    """Alerts of every published closure that have not ended at `at` (default: now)."""
    at = at or config.now()
    out: list[Alert] = []
    for stored in state.list_all("published"):
        for raw in stored.get("alerts") or []:
            alert = Alert.model_validate(raw)
            if _active(alert, at):
                out.append(alert)
    return out


def feed_bytes(at: datetime | None = None) -> bytes:
    at = at or config.now()
    return feed_message(published_alerts(at), at).SerializeToString()


# --- validation ------------------------------------------------------------------------

_jobs: dict[str, threading.Thread] = {}
_jobs_lock = threading.Lock()


def _validate_and_store(closure_id: str) -> FeedValidation:
    result = validate_feed(feed_bytes(), closure_id)
    if state.exists("published", closure_id):
        state.write("published", closure_id, result, PART_VALIDATION)
    return result


def _run_job(closure_id: str) -> None:
    try:
        _validate_and_store(closure_id)
    except Exception:  # noqa: BLE001 - logged; the GET retries synchronously
        log.exception("feed validation failed for %s", closure_id)


def start_validation(closure_id: str) -> threading.Thread:
    with _jobs_lock:
        job = _jobs.get(closure_id)
        if job is not None and job.is_alive():
            return job
        job = threading.Thread(target=_run_job, args=(closure_id,), daemon=True,
                               name=f"validate-{closure_id}")
        _jobs[closure_id] = job
        job.start()
        return job


def get_validation(closure_id: str, wait_seconds: float = 120.0) -> FeedValidation:
    """The validator result for the feed as it was right after this closure's publish."""
    closure_or_404(closure_id)
    if not state.exists("published", closure_id):
        raise not_found(f"Closure {closure_id!r} is not published.", "NOT_PUBLISHED")
    job = _jobs.get(closure_id)
    if job is not None and job.is_alive():
        job.join(wait_seconds)
    stored = state.read("published", closure_id, PART_VALIDATION)
    if stored is None:
        return _validate_and_store(closure_id)
    return FeedValidation.model_validate(stored)
