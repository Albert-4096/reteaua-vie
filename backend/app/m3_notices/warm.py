"""`make precompute` hook: build the neighbourhood notices of the prepared cases (read-only, no publish)."""

from __future__ import annotations

import logging

log = logging.getLogger("reteaua_vie.m3")


def warm(closure_ids: list[str]) -> None:
    from app.m3_notices import notices

    for cid in closure_ids:
        try:
            out = notices.notices_for(cid)
            log.info("notices %s: %d zones", cid, len(out))
        except Exception:  # noqa: BLE001 - a closure that is not analyzed yet is skipped
            log.exception("notices warm-up failed for %s", cid)
