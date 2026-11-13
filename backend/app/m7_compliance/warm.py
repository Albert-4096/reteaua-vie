"""`make precompute` hook: the history back-fill and the indicators, cached so step 5 opens at once.

It reads only; it never publishes a prepared case (they stay `analyzed`, D-011). The DATEX feed
and the compliance table are built per request (no heavy data), so they need no warm-up.
"""

from __future__ import annotations

import logging

log = logging.getLogger("reteaua_vie.m7")


def warm(closure_ids: list[str]) -> None:
    from app.m7_compliance import history, indicators

    bf = history.backfill()
    log.info("history back-fill: %d rows, %d posts unread", len(bf.entries), len(bf.unread))
    ind = indicators.indicators()
    log.info("indicators: %d, %d null", len(ind.indicators), sum(i.value is None for i in ind.indicators))
