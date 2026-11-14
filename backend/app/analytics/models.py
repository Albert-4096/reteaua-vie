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


# --- L3: line reliability, measured from the recording (via L0) -------------------------------


class Punctuality(Model):
    n: int                              # observed stop events with a delay
    trips: int                          # trip runs they come from (the blocks of the interval)
    medianSec: float | None
    p90Sec: float | None
    early: float | None                 # share earlier than -60 s
    onTime: float | None                # -60 s .. +300 s
    late: float | None                  # +300 s .. +600 s
    veryLate: float | None              # over +600 s
    ci: list[float] | None              # 95 % interval of `onTime`, bootstrap with one trip as a block
    conclusive: bool                    # false = „neconcludent” (under MIN_TRIPS trips or MIN_EVENTS events)


class HeadwayStats(Model):
    pairs: int                          # consecutive scheduled trips both observed at the reference stop
    refStopId: str | None
    medianRealMin: float | None
    medianSchedMin: float | None
    cvReal: float | None                # spread of real headways / their mean
    cvSched: float | None
    ewtMin: float | None                # extra wait of a random rider: real minus scheduled


class BunchingStats(Model):
    events: int                         # observed stop events
    bunched: int                        # with another vehicle of the same line and direction within `thresholdSec`
    share: float | None
    thresholdSec: int


class TripsVsTimetable(Model):
    scheduled: int                      # trips judged: observed + missed (O2's rule)
    observed: int
    missed: int                         # no vehicle seen in the live data (we do not say „neefectuată”)
    unknown: int                        # not judged (outside the recording, too recent)
    share: float | None                 # observed / scheduled


class HourReliability(Model):
    hour: int                           # local hour of the stop event (trips: of the scheduled start)
    punctuality: Punctuality
    headway: HeadwayStats
    bunching: BunchingStats
    trips: TripsVsTimetable


class LineReliability(Model):
    routeId: str
    shortName: str
    mode: Literal["tram", "bus", "trolleybus", "other"]
    punctuality: Punctuality
    headway: HeadwayStats
    bunching: BunchingStats
    trips: TripsVsTimetable
    hours: list[HourReliability]


class Thresholds(Model):
    earlySec: int
    onTimeMaxSec: int
    lateMaxSec: int
    bunchingSec: int
    minTrips: int
    minEvents: int


class ReliabilityResponse(Model):
    recording: Recording
    thresholds: Thresholds
    lines: list[LineReliability]
    wording: I18n                       # „estimare din datele live, nu raportul oficial”
    method: I18n
    caveat: I18n
    provenance: list[Provenance]


class VehicleHealth(Model):
    vehicleId: str
    routes: list[str]                   # short names of the lines it ran
    reports: int
    lastReportAt: IsoTime
    silentGaps: int                     # mid-trip pauses in its reports of at least `gapMin` minutes
    longestGapMin: float | None
    frozenEpisodes: int                 # standing still between stops for at least `gapMin` minutes
    longestFrozenMin: float | None
    longestMin: float                   # the larger of the two
    longestAt: IsoTime | None
    toToleranceMin: float               # minutes left before 120 (0 = reached); the contract tolerance is de verificat
    status: Literal["de verificat", "de urmărit"]


class VehicleHealthResponse(Model):
    recording: Recording
    gapMin: int
    checkMin: int                       # at or above: „de verificat”
    toleranceMin: int
    vehiclesSeen: int
    vehicles: list[VehicleHealth]       # longest first; only vehicles with an episode
    wording: I18n
    method: I18n
    caveat: I18n
    provenance: list[Provenance]


# --- R8 / L4: critical streets and where public transport stands -------------------------------


class StreetSection(Model):
    id: str                             # "<fromStopId>><toStopId>"
    fromStop: CorridorStop
    toStop: CorridorStop
    lengthMeters: int | None
    lines: list[str]                    # short names of the lines that use the section
    departuresPerDay: int               # scheduled trips over the section on the reference service day
    runs: int                           # recorded runs over it (both ends observed, not interpolated)
    lostMin: float | None               # Σ of the positive growth of the delay over the section; null = no recorded run
    lostMinPerHour: float | None        # per recorded hour
    medianGrowthSec: float | None       # median growth of the delay per run (negative = the bus gains time)
    conclusive: bool
    rank: int | None                    # by lostMin among sections with a conclusive figure


class CriticalStreetsResponse(Model):
    recording: Recording
    date: str                           # reference service day of `departuresPerDay`
    minRuns: int
    sections: list[StreetSection]
    wording: I18n
    method: I18n
    caveat: I18n
    provenance: list[Provenance]


class StandingPoint(Model):
    cellId: str                         # 100 m cell of the UTM 34N grid: "<x>_<y>"
    location: list[float]
    minutes: float                      # vehicle-minutes standing there, whole recording
    minutesPerHour: float               # per recorded hour
    samples: int
    vehicles: int
    days: int                           # recorded days with a sample
    lines: list[str]
    departuresPerDay: int | None        # scheduled trips of those lines, both directions (weight)
    nearestStopMeters: int
    cause: Literal["semafor la cel mult 50 m", "coadă / altă cauză"]
    hours: dict[str, float]             # local hour -> vehicle-minutes


class StandingResponse(Model):
    recording: Recording
    date: str
    stopDistanceMeters: int
    speedMaxMps: float
    signalMeters: int
    points: list[StandingPoint]         # most vehicle-minutes first
    totalMinutes: float
    wording: I18n
    method: I18n
    caveat: I18n
    provenance: list[Provenance]


# --- R23: cut-through neighbourhood streets ----------------------------------------------------


class StandingEvidence(Model):
    minutes: float                      # vehicle-minutes standing within 60 m (L4 cells, top 300 only)
    cells: int
    label: I18n                         # „din N ore înregistrate (…); date de sprijin, nu dovadă”


class CutThroughStreet(Model):
    rank: int
    name: str | None
    roadClass: str | None               # OSM highway of the way the edge runs on; null = „necunoscut”
    neighbourhood: bool                 # residential or living_street: „stradă de cartier”
    residentsAlong: int                 # GHSL residents in cells within 50 m (a model, not a census)
    lines: list[str]                    # short names of the lines that run on it
    changePct: float                    # change of the street's structural load (detour-load), not traffic
    geometry: dict                      # GeoJSON LineString, WGS84
    standing: StandingEvidence | None


class CutThrough(Model):
    closureId: str
    streets: list[CutThroughStreet]     # same order as the detour-load edges
    neighbourhoodStreets: int
    residentsAlongNeighbourhood: int
    label: I18n                         # network structure, not traffic volumes
    commission: I18n                    # „acces riverani + semnalizarea ocolirii oficiale”: a proposal, not a decision
    method: I18n
    provenance: list[Provenance]


# --- R24: works balance ------------------------------------------------------------------------


class BalanceFigure(Model):
    id: str
    label: I18n
    planned: str | None                 # what was planned, in words, with its source
    measured: str | None                # what the recording shows; null = „necunoscut”
    value: float | None
    n: int | None
    conclusive: bool | None             # false = „neconcludent”
    window: I18n | None                 # the recording window label
    source: str
    detail: dict | None = None


class WorksBalance(Model):
    closureId: str
    title: I18n
    windowStart: IsoTime
    windowEnd: IsoTime
    windowEnded: bool                   # the row is final only after the window ends
    recording: Recording
    figures: list[BalanceFigure]
    wording: I18n
    caveat: I18n
    provenance: list[Provenance]
