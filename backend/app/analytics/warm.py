"""`make precompute` hook: fill the coverage (A10) and corridor (A8) caches for the three day types."""

from __future__ import annotations

import logging

from app.analytics import corridors, coverage

log = logging.getLogger("reteaua_vie.analytics")


def warm(closure_ids: list[str]) -> None:
    for day in coverage.DAYS:
        try:
            coverage.summary(day)
            n = corridors.corridors(day, limit=1)["count"]
            log.info("analytics: %s coverage and %d corridors ready", day, n)
        except Exception:  # a feed without that day type must not stop the precompute
            log.exception("analytics warm-up failed for %s", day)
