"""C1/C2 types: a check-in (a proof that a vehicle runs, not the official validation) and what it confirms."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.models.base import I18n, IsoTime, Model, Provenance
from app.models.service_confirmation import ServiceConfirmation  # noqa: F401  (re-export)


class CheckinInput(Model):
    stickerId: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,40}$")
    at: IsoTime | None = None                       # default: now; at most 48 h in the past
    lat: float | None = Field(None, ge=-90, le=90)  # the position at that moment only; both or none
    lon: float | None = Field(None, ge=-180, le=180)
    deviceKey: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")   # random id of the browser


class CheckinAck(Model):
    routeId: str
    shortName: str | None
    directionId: int
    tripId: str
    stopId: str | None
    stopName: str | None
    method: Literal["position", "time"]             # how the trip was chosen
    distanceToRouteMeters: int | None               # null without a position
    at: IsoTime
    simulated: bool                                 # a „simulare” sticker
    label: I18n | None                              # „simulare” when simulated
    provenance: list[Provenance]


class TripCount(Model):
    tripId: str
    count: int
    distinctDevices: int | None                     # null once the raw rows are gone (counts only)
    simulated: int                                  # how many of `count` came through a „simulare” sticker
    firstAt: IsoTime | None
    lastAt: IsoTime | None


class StopCount(Model):
    stopId: str
    stopName: str | None
    count: int
    simulated: int


class LineCheckins(Model):
    routeId: str
    shortName: str | None
    total: int
    simulated: int
    trips: list[TripCount]
    stops: list[StopCount]


class CheckinCounts(Model):
    window: dict                                    # {start, end}
    lines: list[LineCheckins]
    total: int
    simulated: int
    note: I18n
    provenance: list[Provenance]
