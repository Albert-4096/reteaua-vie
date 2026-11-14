"""`make precompute` hook: fill the coverage (A10) and corridor (A8) caches for the three day types."""

from __future__ import annotations

import logging

from app.analytics import corridors, coverage, gps_health, reliability, streets

log = logging.getLogger("reteaua_vie.analytics")


def warm(closure_ids: list[str]) -> None:
    for day in coverage.DAYS:
        try:
            coverage.summary(day)
            n = corridors.corridors(day, limit=1)["count"]
            log.info("analytics: %s coverage and %d corridors ready", day, n)
        except Exception:  # a feed without that day type must not stop the precompute
            log.exception("analytics warm-up failed for %s", day)
    for name, fn in (("reliability", reliability.report), ("gps health", gps_health.report),
                     ("critical streets", streets.critical_streets), ("standing", streets.standing)):
        try:
            fn()
        except Exception:  # L0 may not be built yet
            log.exception("analytics warm-up failed for %s", name)
    from app.analytics import balance, cutthrough
    from app.analytics.models import WorksBalance
    from app.common import jobs
    from app.m7_compliance.datex import published_closures

    for pc in published_closures(active_only=False):
        try:
            cid = pc.closure["id"]
            jobs.compute_and_cache(cutthrough.job_key(cid), lambda cid=cid: cutthrough.build(cid))
        except Exception:
            log.exception("analytics warm-up failed for cut-through %s", pc.closure.get("id"))
        try:
            jobs.compute_and_cache(balance.job_key(cid), lambda cid=cid: WorksBalance.model_validate(balance.balance(cid)))
        except Exception:
            log.exception("analytics warm-up failed for balance %s", pc.closure.get("id"))
