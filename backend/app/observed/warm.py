"""`make precompute` hook: build the hours of the observed timetable (L0) not built yet."""

from __future__ import annotations

import logging

from app.observed import build

log = logging.getLogger("reteaua_vie.observed")


def warm(closure_ids: list[str]) -> None:
    n = build.build()
    log.info("observed: %d hour(s) built, %d built in all", n, len(build.read_manifest().get("hours", {})))
