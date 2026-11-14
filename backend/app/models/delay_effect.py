"""CONTRACT v2.37 types of GET /api/closures/{id}/delay-effect and R18 `delayEffect` (R25)."""

from __future__ import annotations

from typing import Literal

from app.models.base import I18n, Model, Provenance

Verdict = Literal["masurat", "neconcludent"]


class DelayEffect(Model):
    n: int                          # trips with a measured value
    addedSec: float | None          # median per trip: delay added over the stretch minus the trip's own drift
    low: float | None               # 95 % bootstrap interval, one trip = one block
    high: float | None
    verdict: Verdict                # neconcludent: n < minTrips, or the interval includes zero
    text: I18n                      # the step 4 row, ready to show


class DelayStretch(Model):
    routeId: str
    shortName: str | None
    directionId: int
    kind: str                       # L1's stretch kind: detour, start_moved, end_moved, truncated_start, ...
    fromStop: str | None            # the stretch's first and last stop as the timetable in force names them
    toStop: str | None
    effect: DelayEffect


class ClosureDelayEffect(Model):
    closureId: str
    status: Literal["ok", "fara_orar_vechi", "fara_schimbare"]
    minTrips: int
    total: DelayEffect              # every stretch's trips pooled
    stretches: list[DelayStretch]
    method: I18n
    provenance: list[Provenance]
