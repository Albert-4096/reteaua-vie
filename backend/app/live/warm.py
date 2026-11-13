"""`make precompute` hook: cache the vehicle recording per hour and check the prepared cases."""

from __future__ import annotations

import logging

from app.common.errors import ApiError
from app.live.check import compute_live_check, warm_recording
from app.live.reports import report_summary

log = logging.getLogger("reteaua_vie.live")


def warm(closure_ids: list[str]) -> None:
    files = warm_recording()
    log.info("live: %d recording files cached per hour", files)
    for cid in closure_ids:
        try:
            live = compute_live_check(cid)
            rep = report_summary(cid)
        except ApiError as exc:  # a case that is not stored or not analyzed yet
            log.warning("live warm-up skipped %s: %s", cid, exc.message)
            continue
        log.info("live %s: source=%s summary=%s; sesizări total=%s", cid, live["source"], live["summary"],
                 rep["total"])
