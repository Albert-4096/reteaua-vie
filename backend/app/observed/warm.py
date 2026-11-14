"""`make precompute` hook: build the hours of the observed timetable (L0) not built yet, then cache
each prepared closure's detour cost (L1-B) for the hours built."""

from __future__ import annotations

import logging

from app.common import jobs, state
from app.observed import build, detour_cost

log = logging.getLogger("reteaua_vie.observed")


def warm(closure_ids: list[str]) -> None:
    n = build.build()
    log.info("observed: %d hour(s) built, %d built in all", n, len(build.read_manifest().get("hours", {})))
    for cid in closure_ids:
        closure = state.read("closures", cid)
        if closure is None:
            continue
        out = jobs.compute_and_cache(detour_cost.job_key(cid), lambda c=closure: detour_cost.compute_detour_cost(c))
        log.info("detour cost %s: %s, %d stretches", cid, out.status, len(out.stretches))
