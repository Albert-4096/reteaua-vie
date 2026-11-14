"""Response types of the CityApp / Timi endpoints (S1)."""

from __future__ import annotations

from typing import Literal

from app.models.base import I18n, IsoTime, Model, Provenance
from app.models.v1 import NearestServed


class LineReason(Model):
    kind: Literal["works"]                   # O2 adds "noVehicle" (see status.live_gap_hook)
    closureId: str
    title: I18n
    action: str | None                       # rerouted | shortened | suspended | ... from the notice
    since: IsoTime
    until: IsoTime
    noticeUrl: str | None                    # the STPT notice the closure was read from


class StopLine(Model):
    routeId: str
    shortName: str
    directionId: int
    headsign: str | None
    stops: Literal["yes", "no", "unconfirmed"]
    reason: LineReason | None                # null when the line stops
    nextDepartureAt: IsoTime | None          # from the timetable, only for lines that stop


class LiveCheck(Model):
    status: Literal["pending", "ok"]
    note: I18n


class StopStatus(Model):
    stopId: str
    name: str
    location: list[float]
    at: IsoTime
    state: Literal["normal", "partial", "suspended", "unknown"]
    lines: list[StopLine]
    nearestServed: NearestServed | None      # null when the stop itself is still served or none within 1,500 m
    sentence: I18n                           # one template sentence, no LLM
    liveFeed: LiveCheck                       # "niciun vehicul în datele live" waits for O2
    provenance: list[Provenance]


class StopHit(Model):
    stopId: str
    name: str
    location: list[float]
    routeIds: list[str]
    distanceMeters: int | None
