"""C2 type, in app.models so the O2 and R2 models can use it without importing app.checkin."""

from __future__ import annotations

from typing import Literal

from app.models.base import I18n, IsoTime, Model


class ServiceConfirmation(Model):
    """C2: „în serviciu, fără date GPS (confirmat de N călători)”."""
    state: Literal["in_serviciu_fara_gps"] = "in_serviciu_fara_gps"
    travelers: int                                  # distinct phones within 10 min on one trip
    trips: list[str]                                # the trips that reached the threshold
    firstAt: IsoTime
    lastAt: IsoTime
    simulated: bool                                 # at least one check-in came through a „simulare” sticker
    label: I18n
