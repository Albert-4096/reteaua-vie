"""Response types of /api/observed/* (CONTRACT v2.13, `ObservedSummary`)."""

from __future__ import annotations

from pydantic import Field

from app.models.base import I18n, IsoTime, Model, Provenance


class ObservedHours(Model):
    from_: IsoTime = Field(alias="from")   # first snapshot of the built hours
    to: IsoTime                            # last snapshot of the built hours
    recordedHours: int                     # (to - from), rounded
    built: int                             # hour files turned into L0
    pending: int                           # hour files not built yet (the open hour, the last one)


class ObservedGap(Model):
    from_: IsoTime = Field(alias="from")
    seconds: int


class ObservedQuality(Model):
    tripsObserved: int                     # (trip, service date) with at least one stop event
    tripsWith80PctStops: int               # ... with >= 80 % of their GTFS stops matched
    shareWith80PctStops: float | None
    tripsInsideRecording: int              # planned start and end inside the recording
    shareWith80PctStopsInside: float | None
    delayPairs: int                        # observed stop events with a feed delaySec
    medianAbsDelayDiffSec: float | None    # |our stop delay - feed delaySec|, observed stops
    medianDelayDiffSec: float | None       # signed (ours - feed)
    medianAbsDelayDiffSecInterpolated: float | None
    tripsAfterMidnight: int                # trips with a stop event after midnight of their service date
    maxGapSec: int                         # no stop event from two reports further apart than this
    gaps: list[ObservedGap]                # pauses of the recording longer than 60 s


class ObservedSummary(Model):
    hours: ObservedHours | None
    snapshots: int
    reports: int                           # de-duplicated on (vehicle, updatedAt)
    vehicles: int
    routes: int
    trips: int                             # trip ids seen in the reports
    stopEvents: int
    interpolatedEvents: int
    interpolatedShare: float | None
    dwellEvents: int
    medianDwellSec: float | None
    segments: int
    quality: ObservedQuality | None
    label: I18n | None                     # „din N ore înregistrate (vin. 13:47 → …)”
    method: I18n
    provenance: list[Provenance]


# --- L1-B: GET /api/closures/{id}/detour-cost (CONTRACT `DetourCost`) ---------------------------------

class Estimate(Model):
    sec: float | None          # median, seconds
    low: float | None          # 90 % bootstrap interval, one trip = one block
    high: float | None
    n: int                     # trips
    conclusive: bool           # n >= minTrips; false = „neconcludent”


class PlannedTimes(Model):
    before: Estimate           # scheduled time over the stretch, timetable before the works
    after: Estimate            # ... timetable in force when they start
    extra: Estimate            # after - before, trip by trip


class DetourStops(Model):
    stopIds: list[str]
    stopNames: list[str]


class DetourHour(Model):
    hour: int                  # Bucharest
    dayType: str               # fri | sat | sun
    n: int
    measuredSec: float | None
    estimatedSec: float | None


class DetourStretch(Model):
    routeId: str
    shortName: str
    directionId: int
    kind: str                  # detour | start_moved | end_moved | truncated_start | truncated_end
    before: DetourStops        # anchors included
    after: DetourStops
    planned: PlannedTimes
    measured: Estimate | None             # L0 run time over `after`; null when `after` is one stop
    measuredVsPlanned: Estimate | None    # measured - planned (timetable in force on the recorded day)
    estimated: Estimate | None            # other lines' speeds on the same streets, at each trip's hour
    estimateError: Estimate | None        # estimated - measured (the back-test)
    coverage: float | None                # share of `after` length with >= 3 other-line runs on the street
    otherRoutes: list[str]
    byHour: list[DetourHour]


class DetourTotals(Model):
    plannedExtra: Estimate
    measuredVsPlanned: Estimate
    estimateError: Estimate


class DetourCost(Model):
    closureId: str
    status: str                # ok | fara_inregistrare | fara_orar_vechi | fara_schimbare
    label: I18n | None         # „din N ore înregistrate (vin. 13:47 → …)”
    finding: I18n | None
    minTrips: int
    feedBefore: str | None
    feedAfter: str | None
    stretches: list[DetourStretch]
    totals: DetourTotals
    method: I18n
    provenance: list[Provenance]
