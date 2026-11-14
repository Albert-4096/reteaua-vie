"""CONTRACT.md v2 types (D-009), with the v2.1 and v2.2 fields."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import Field, model_validator

from app.models.base import (
    Feature,
    I18n,
    IsoTime,
    LineString,
    LonLat,
    Model,
    Provenance,
    Window,
)
from app.models.v1 import ClosureStatus, Impact
from app.models.live_missing import MissingOverview

LtsValue = Literal[1, 2, 3, 4]


class ClosureSummary(Model):
    id: str
    title: I18n
    status: ClosureStatus
    window: Window
    routeIds: list[str]
    zoneSlugs: list[str]
    stopsSuspended: int | None
    departuresLost: int | None
    publishedAt: IsoTime | None
    reconstructed: bool | None = None       # v2.8: see Closure.reconstructed
    reconstructedNote: I18n | None = None


class ComplianceCounts(Model):
    covered: int
    partial: int
    missing: int


class Overview(Model):
    at: IsoTime
    activeClosures: list[ClosureSummary]
    upcomingClosures: list[ClosureSummary]
    ghostDeparturesToday: int | None
    vehiclesLive: int | None
    vehiclesAt: IsoTime | None
    compliance: ComplianceCounts | None  # v2.3: null until M7 serves counts
    provenance: list[Provenance]
    missingLines: MissingOverview | None = None  # v2.13 (O2): lines with no vehicle in our live recording


# --- layers -----------------------------------------------------------------------


class BikeProps(Model):
    kind: Literal["lane", "parking", "share_station"]
    osmId: str
    name: str | None
    lts: LtsValue | None


class ParkingProps(Model):
    kind: Literal["zone", "street", "lot"]
    id: str
    name: str
    tariff: str


class DestinationProps(Model):
    kind: Literal["hospital", "school", "rail_station", "landmark"]
    osmId: str
    name: str | None


class PopulationProps(Model):
    cellId: str
    residents: float


class VehicleProps(Model):
    vehicleId: str
    routeId: str | None
    tripId: str | None
    directionId: Literal[0, 1] | None
    stopId: str | None
    status: str | None
    delaySec: int | None
    wheelchair: bool | None
    updatedAt: IsoTime | None
    headsign: str | None = None  # additive, optional
    bearing: float | None = None  # additive, optional


LAYER_PROPS: dict[str, type[Model]] = {
    "bike": BikeProps,
    "parking": ParkingProps,
    "destinations": DestinationProps,
    "population": PopulationProps,
    "vehicles": VehicleProps,
}


class LayerCollection(Model):
    """GeoJSON FeatureCollection + foreign members `layer` and `provenance`."""

    type: Literal["FeatureCollection"]
    layer: str
    features: list[Feature]
    provenance: list[Provenance]

    @model_validator(mode="after")
    def _check_props(self):
        props_model = LAYER_PROPS.get(self.layer)
        if props_model is not None:
            for f in self.features:
                props_model.model_validate(f.properties)
        return self


# --- module results -----------------------------------------------------------------


class BikeLane(Model):
    osmId: str
    name: str | None
    lengthMeters: float
    geometry: LineString


class BikeParking(Model):
    osmId: str
    capacity: int | None
    location: LonLat


class BikeDetour(Model):
    name: str | None
    lts: LtsValue | None
    lengthMeters: float
    geometry: LineString


class BikeDetourSummary(Model):
    """v2.32 (R16): the bike detour split by stress, surface and tram-rail crossings; unknown stays unknown."""

    lengthMeters: float
    byLts: dict[str, float]  # "1".."4" and "unknown", metres
    highStressMeters: float  # LTS 3-4
    roughMeters: float  # OSM surface sett/cobblestone/gravel/dirt/... or smoothness bad or worse
    surfaceUnknownMeters: float  # neither surface nor smoothness is tagged
    tramCrossings: int  # the detour crosses a GTFS tram shape (points within 15 m counted once)
    unknownSharePct: int  # share of the length whose LTS is unknown
    tooLittleData: bool  # unknown share above 50 %
    sentence: I18n


class ShareStation(Model):
    osmId: str
    name: str | None
    meters: int  # straight line from the stop


class ShareAlternative(Model):
    """v2.32 (R17): bike-share stations near the two ends of a suspended section, and the bike route between them."""

    fromStopId: str
    fromStopName: str
    toStopId: str
    toStopName: str
    routeIds: list[str]
    stationFrom: ShareStation | None
    stationTo: ShareStation | None
    routeLengthMeters: float | None
    highStressMeters: float | None
    line: I18n | None  # null unless both stations, distinct, and a route exist


class BikeImpact(Model):
    closureId: str
    lanesAffected: list[BikeLane]
    parkingAffected: list[BikeParking]
    detourStress: list[BikeDetour]
    provenance: list[Provenance]
    detourSummary: BikeDetourSummary | None = None
    shareAlternative: list[ShareAlternative] = []
    shareNote: I18n | None = None


class ParkingFeatureRef(Model):
    id: str
    name: str
    tariff: str
    geometry: dict[str, Any]


class ParkAndRide(Model):
    stopId: str
    name: str
    routeIds: list[str]
    lotId: str | None
    walkMeters: float | None


class ParkingImpact(Model):
    closureId: str
    streetsAffected: list[ParkingFeatureRef]
    lotsAffected: list[ParkingFeatureRef]
    parkAndRide: list[ParkAndRide]
    provenance: list[Provenance]


class AccessTotals(Model):
    residentsBefore: int | None
    residentsAfter: int | None
    residentsLosing: int | None


class AccessZone(AccessTotals):
    slug: str
    name: str


class AccessImpact(Model):
    closureId: str
    dest: Literal["hospital", "school", "rail_station", "landmark"]
    minutes: int
    at: IsoTime
    totals: AccessTotals
    byZone: list[AccessZone]
    estimate: Literal[True]
    method: I18n
    provenance: list[Provenance]


class DetourEdge(Model):
    name: str | None
    geometry: LineString
    centralityBefore: float
    centralityAfter: float
    changePct: float
    routeIdsOnEdge: list[str]


class Spillover(Model):
    meanDelaySecOnEdges: float
    meanDelaySecNetwork: float
    hours: float
    from_: IsoTime = Field(alias="from")
    to: IsoTime
    label: I18n


class DetourLoad(Model):
    closureId: str
    edges: list[DetourEdge]
    routesSlowedRisk: list[str]
    label: I18n
    spillover: Spillover | None = None  # v2.1
    provenance: list[Provenance]


class Conflict(Model):
    closureId: str
    otherClosureId: str
    otherTitle: I18n
    overlap: Window
    kind: Literal["same_corridor", "shared_detour", "same_stops"]
    stopIds: list[str]
    routeIds: list[str]


class ReportCategory(Model):
    category: str
    count: int
    resolved: int


class ReportSummary(Model):
    closureId: str
    radiusMeters: float
    from_: IsoTime = Field(alias="from")
    to: IsoTime
    total: int | None  # v2.3: null when our recording does not cover the period
    byCategory: list[ReportCategory]
    provenance: list[Provenance]
    coveredFrom: IsoTime | None = None  # v2.3: what the sesizări recording covers
    coveredTo: IsoTime | None = None  # v2.3
    note: I18n | None = None  # v2.3


class WindowCandidate(Model):
    window: Window
    departuresLost: int
    residentsLosingStop: int | None
    conflicts: int
    rank: int
    note: I18n | None = None  # v2.3: plain-words explanation of this window


class WindowPhase(Model):
    phase: int
    section: LineString
    window: Window
    departuresLost: int


class CommonConflict(Model):
    """v2.5: another closure that overlaps every candidate window (it cannot change the ranking)."""

    closureId: str
    title: I18n | None
    window: Window


class WindowSuggestion(Model):
    closureId: str
    hours: float
    searchFrom: IsoTime
    searchTo: IsoTime
    candidates: list[WindowCandidate] = Field(max_length=10)
    best: Window
    phases: list[WindowPhase] | None = None  # v2.1
    method: I18n
    provenance: list[Provenance]
    # v2.5: departures lost in the closure's own window with the same decisions (= Impact.totals.departuresLost)
    baselineDeparturesLost: int | None = None
    # v2.5: closures overlapping the whole search range, said once here and not counted in candidates[].conflicts
    commonConflicts: list[CommonConflict] | None = None


# --- scenarios ---------------------------------------------------------------------


class MitigationFrequency(Model):
    kind: Literal["frequency"]
    routeId: str
    headwayMinutes: float


class MitigationWindow(Model):
    kind: Literal["window"]
    start: IsoTime
    end: IsoTime


class MitigationBikeLane(Model):
    kind: Literal["bike_lane"]
    geometry: LineString


class MitigationParkAndRide(Model):
    kind: Literal["park_and_ride"]
    stopId: str
    lotId: str | None


class MitigationSegment(Model):
    kind: Literal["segment"]
    geometry: LineString


Mitigation = Annotated[
    Union[MitigationFrequency, MitigationWindow, MitigationBikeLane, MitigationParkAndRide, MitigationSegment],
    Field(discriminator="kind"),
]


class ScenarioInput(Model):
    closureId: str
    title: I18n
    mitigations: list[Mitigation]


class Scenario(ScenarioInput):
    id: str
    createdAt: IsoTime


class ScenarioSummary(Model):
    residentsLosingStop: int | None
    residentsLosingAccess: int | None
    departuresLost: int | None  # v2.3: null outside every timetable we hold


class ScenarioNote(Model):
    """v2.3: one plain-words note on a scenario (e.g. „+N plecări (simulare)”)."""

    kind: Literal["frequency", "window", "bike_lane", "park_and_ride", "segment", "none"]
    text: I18n
    value: float | None = None
    unit: str | None = None


class ScenarioImpact(Model):
    scenarioId: str
    closureId: str
    impact: Impact
    access: AccessImpact | None
    detourLoad: DetourLoad | None
    summary: ScenarioSummary
    provenance: list[Provenance]
    notes: list[ScenarioNote] | None = None  # v2.3
    bike: BikeImpact | None = None  # v2.3: bike numbers for a bike_lane mitigation


class ScenarioCompare(Model):
    a: ScenarioImpact
    b: ScenarioImpact


# --- publish outputs ---------------------------------------------------------------


class NoticeStreet(Model):
    name: str
    codGis: str | None


class ZoneNotice(Model):
    id: str
    closureId: str
    zoneSlug: str
    zoneName: str
    streets: list[NoticeStreet]
    window: Window
    title: I18n
    body: I18n
    stopIds: list[str]
    routeIds: list[str]
    alertIds: list[str]
    publishedAt: IsoTime | None  # v2.3: null before the closure is published


class RouteLeg(Model):
    mode: Literal["walk", "tram", "bus", "trolleybus"]
    routeId: str | None
    fromStopId: str | None
    toStopId: str | None
    departAt: IsoTime
    arriveAt: IsoTime
    geometry: LineString


class RoutePlan(Model):
    from_: LonLat = Field(alias="from")
    to: LonLat
    at: IsoTime
    legs: list[RouteLeg]
    durationMinutes: float
    avoidedStopIds: list[str]
    provenance: list[Provenance]


# --- report -----------------------------------------------------------------------


class Obligation(Model):
    id: str
    act: str
    requirement: I18n
    deadline: str | None
    owner: I18n
    status: Literal["covered", "partial", "missing"]
    coveredBy: list[str]
    note: I18n | None


class ComplianceReport(Model):
    generatedAt: IsoTime
    obligations: list[Obligation]
    provenance: list[Provenance]


class HistoryEntry(Model):
    closureId: str
    title: I18n
    window: Window
    publishedAt: IsoTime
    alertsCount: int | None
    stopsSuspended: int | None
    departuresLost: int | None
    routeIds: list[str]
    note: I18n | None = None  # v2.3: e.g. „reconstituit din anunț STPT, nu publicat prin platformă”
    sourceUrl: str | None = None  # v2.3: the STPT post a back-filled row comes from
    provenance: list[Provenance] | None = None  # v2.3


class Indicator(Model):
    code: str
    name: I18n
    value: float | None
    unit: str
    method: I18n
    scope: str


class IndicatorSet(Model):
    generatedAt: IsoTime
    indicators: list[Indicator]
    provenance: list[Provenance]


class ExportFile(Model):
    name: str
    format: Literal["GTFS-RT", "DATEX II", "JSON", "mobilityDCAT-AP", "NGSI-LD"]  # v2.5: NGSI-LD
    standard: str
    url: str
    updatedAt: IsoTime | None


# --- feed validation (v2.3) --------------------------------------------------------


class ValidationRule(Model):
    id: str
    severity: Literal["ERROR", "WARNING", "INFO"]
    title: str
    description: str | None
    occurrences: int
    examples: list[str]
    note: I18n | None = None


class ValidatorTool(Model):
    name: str
    version: str | None
    source: str | None


class FeedValidation(Model):
    """CONTRACT 2.3: what the „validator pe ecran” panel shows (GET /api/closures/{id}/validation)."""

    closureId: str | None
    method: Literal["validator", "internal"]
    label: I18n
    tool: ValidatorTool | None
    ranAt: str
    durationSec: float
    passed: bool
    errorCount: int
    warningCount: int
    rules: list[ValidationRule]
    feed: dict
    gtfs: dict
    fallbackReason: str | None
    provenance: list[Provenance]



# --- jobs --------------------------------------------------------------------------


class JobError(Model):
    code: str
    message: str


class Job(Model):
    jobId: str
    state: Literal["queued", "running", "done", "error"]
    progress: float | None
    result: dict[str, Any] | list[Any] | None
    error: JobError | None


class JobAccepted(Model):
    jobId: str


class ScanStop(Model):
    """v2.4 (R7): poster scans of one stop. Counts only, no visitor data."""

    stopId: str
    count: int
    firstBucket: str  # hour bucket, Europe/Bucharest, e.g. 2026-11-14T12:00+02:00
    lastBucket: str


class ScanCounts(Model):
    closureId: str
    total: int
    bucket: Literal["hour"] = "hour"
    stops: list[ScanStop]
    provenance: list[Provenance]


class ScanAck(Model):
    ok: bool = True
    closureId: str
    stopId: str


class LandmarkStop(Model):
    stopId: str
    name: str
    meters: int


class LandmarkItem(Model):
    id: str
    name: str  # exactly as the City Hall gives it
    nameEn: str | None
    address: str | None
    nearestStop: LandmarkStop | None
    losesService: bool  # the nearest stop is one that loses service in this closure
    nearestServed: LandmarkStop | None  # nearest stop that keeps its service, for the English poster line


class LandmarkImpact(Model):
    closureId: str
    total: int
    losingNearestStop: int
    items: list[LandmarkItem]
    summary: I18n
    provenance: list[Provenance]


class PaidMeasure(Model):
    count: int
    meters: int | None  # streets: metres of paid street inside the closure buffer
    squareMeters: int | None  # car parks: area of each car park that touches the buffer
    byTariff: dict[str, int]  # colour -> metres (streets) or m² (car parks)


class PaidParking(Model):
    closureId: str
    window: Window
    streets: PaidMeasure
    lots: PaidMeasure
    paidHours: float  # hours of the window in which at least one affected tariff colour is charged
    paidHoursByTariff: dict[str, float]
    uncheckedFeatures: int  # affected features the City Hall file does not mark as checked
    parkAndRide: list[ParkAndRide]
    noticeLine: I18n
    note: I18n
    provenance: list[Provenance]
