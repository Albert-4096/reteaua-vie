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


# --- A10: coverage per neighbourhood ---------------------------------------------------------


class CoverageClass(Model):
    id: Literal["none", "lt2", "2to4", "4to8", "ge8"]
    label: I18n
    minPerHour: float                   # lower bound, departures per hour (inclusive)
    maxPerHour: float | None            # upper bound (exclusive); null = open


class ZoneCoverage(Model):
    slug: str                           # "_outside" = cells outside the 40 neighbourhoods
    name: str
    residents: int                      # GHSL residents inside the zone (a model, not a census)
    byClass: list[int]                  # residents per class, same order as `classes`
    weakResidents: int                  # classes none + lt2: „acoperire slabă cu transport public”
    weakShare: float | None
    medianPerHour: float | None         # residents-weighted median of departures per hour
    rank: int | None                    # 1 = most residents with weak coverage; null for _outside


class CoverageSummary(Model):
    day: Literal["weekday", "saturday", "sunday"]
    date: str                           # the feed's service day the counts come from
    hours: list[int]                    # [from, to) local hours of the window
    walkMeters: int
    classes: list[CoverageClass]
    city: ZoneCoverage                  # all residents of the grid (zones + outside)
    zones: list[ZoneCoverage]           # sorted by weakResidents, most first
    method: I18n
    caveat: I18n
    provenance: list[Provenance]


# --- A8: lines on the same corridor ---------------------------------------------------------


class CorridorLine(Model):
    routeId: str
    shortName: str
    mode: Literal["tram", "bus", "trolleybus", "other"]


class CorridorStop(Model):
    stopId: str
    name: str


class LineShift(Model):
    routeId: str
    shortName: str
    shiftMin: int                       # minutes later (+) or earlier (-) than the timetable


class OffsetProposal(Model):
    label: I18n                         # „propunere de decalaj, de verificat de SMTT”
    shifts: list[LineShift]             # the first line stays; the others move
    cvAfter: float
    maxGapAfterMin: float


class CorridorHour(Model):
    hour: int
    departures: int                     # all lines together at the first shared stop
    perLine: dict[str, int]             # routeId -> departures
    meanGapMin: float | None
    minGapMin: float | None
    maxGapMin: float | None
    closeGaps: int                      # gaps of at most 2 min: vehicles that come together
    cv: float | None                    # spread of the gaps / their mean; 0 = even
    pattern: Literal["alternează", "mixt", "în pluton"] | None   # null under 3 departures
    proposal: OffsetProposal | None


class Corridor(Model):
    id: str
    lines: list[CorridorLine]
    stops: list[CorridorStop]
    lengthMeters: int
    hours: list[CorridorHour]
    bunchedHours: int                   # hours with pattern „în pluton”
    shiftableHours: int                 # hours with a proposal


class CorridorsResponse(Model):
    day: Literal["weekday", "saturday", "sunday"]
    date: str
    minStops: int
    count: int                          # corridors before `limit`
    corridors: list[Corridor]           # most bunched hours first
    method: I18n
    caveat: I18n
    provenance: list[Provenance]
