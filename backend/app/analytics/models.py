"""Response types of /api/accessibility/* (R6), /api/coverage/* (A10), /api/corridors (A8)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.models.base import I18n, IsoTime, Model, Provenance


class Recording(Model):
    from_: IsoTime | None = Field(alias="from")
    to: IsoTime | None
    hours: int
    label: I18n | None                  # „din N ore înregistrate (vin. 13:47 → sâm. 13:05)”


class HourShare(Model):
    hour: int                           # local hour of the trip's first report, 0-23
    trips: int                          # trips with a known flag (the n of the share)
    stepFree: int
    share: float | None


class Fleet(Model):
    vehicles: int                       # distinct vehicle ids with a known flag
    stepFree: int                       # ... flagged wheelchair=true
    share: float | None
    unknown: int                        # vehicles that never reported the flag


class AccessLine(Model):
    routeId: str
    shortName: str
    mode: Literal["tram", "bus", "trolleybus", "other"]
    trips: int                          # recorded trips with a known flag
    stepFree: int
    share: float | None
    unknown: int                        # recorded trips without the flag
    vehicles: int
    hours: list[HourShare]              # only hours with at least one trip


class AccessibilityLines(Model):
    recording: Recording
    trips: HourShare | None             # hour = -1: all hours
    fleet: Fleet
    byHour: list[HourShare]
    lines: list[AccessLine]
    method: I18n
    caveat: I18n
    provenance: list[Provenance]


class SignalCrossing(Model):
    osmId: str
    distanceMeters: int
    sound: Literal["yes", "no"] | None  # null = the OSM tag is missing: „necunoscut”


class StopAccessibility(Model):
    stopId: str
    name: str
    location: list[float]
    stepFreeWaitMin: float | None       # typical wait for the next step-free vehicle, minutes
    anyWaitMin: float | None            # same for any vehicle, from the same events
    stepFreeEvents: int
    allEvents: int
    nextStepFreeLines: list[str]        # short names of the lines whose step-free vehicles stopped here
    crossing: SignalCrossing | None     # nearest signalised crossing within 100 m
    recording: Recording
    method: I18n
    caveat: I18n
    provenance: list[Provenance]
