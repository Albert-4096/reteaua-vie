"""`make precompute` hook: build the OSM names cache and the parking answer of the prepared cases."""

from __future__ import annotations

import logging

log = logging.getLogger("reteaua_vie.m6")


def warm(closure_ids: list[str]) -> None:
    from app.m6_parking import parking

    parking.warm_caches()
    for cid in closure_ids:
        try:
            r = parking.parking_impact(cid)
            log.info("parking %s: %d streets, %d lots, %d P&R", cid, len(r.streetsAffected),
                     len(r.lotsAffected), len(r.parkAndRide))
        except Exception:  # noqa: BLE001 - one case must not stop the others
            log.exception("parking warm-up failed for %s", cid)
