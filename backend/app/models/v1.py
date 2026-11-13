"""CONTRACT.md v1 types (+ the v2.1 / v2.2 optional fields on them)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.models.base import (
    FeatureCollection,
    I18n,
    IsoDate,
    IsoTime,
    LineGeometry,
    LineString,
    LonLat,
    Model,
    Provenance,
    Window,
)

DirectionId = Literal[0, 1]

ReasonCode = Literal[
    "IN_BUFFER",
    "ON_ROUTE_PATH",
    "DIRECTION_MATCH",
    "DIRECTION_UNCLEAR",
    "EDGE_OF_BUFFER",
    "DUPLICATE_STOP_NAME",
    "NAMED_IN_NOTICE",
    "NOT_NAMED_IN_NOTICE",
    "ROUTE_NOT_IN_NOTICE",
]

# GTFS-RT enum names (gtfs-realtime.proto, Alert.Cause / Alert.Effect).
AlertCause = Literal[
    "UNKNOWN_CAUSE", "OTHER_CAUSE", "TECHNICAL_PROBLEM", "STRIKE", "DEMONSTRATION", "ACCIDENT",
    "HOLIDAY", "WEATHER", "MAINTENANCE", "CONSTRUCTION", "POLICE_ACTIVITY", "MEDICAL_EMERGENCY",
]
AlertEffect = Literal[
    "NO_SERVICE", "REDUCED_SERVICE", "SIGNIFICANT_DELAYS", "DETOUR", "ADDITIONAL_SERVICE",
    "MODIFIED_SERVICE", "OTHER_EFFECT", "UNKNOWN_EFFECT", "STOP_MOVED", "NO_EFFECT",
    "ACCESSIBILITY_ISSUE",
]

ClosureStatus = Literal["draft", "analyzed", "published"]


# --- health / network ---------------------------------------------------------


class Health(Model):
    ok: bool
    feedVersion: str | None
    dataFetchedAt: IsoTime | None
    dataFrozenAt: IsoTime | None = None
    demoNow: IsoTime | None = None
    modulesFailed: list[str] | None = None  # v2.3: api modules that failed to import (skipped)


class NetworkRoute(Model):
    id: str
    shortName: str
    longName: str
    type: int
    color: str
    textColor: str


class NetworkStop(Model):
    id: str
    name: str
    code: str | None
    lat: float
    lon: float
    routeIds: list[str]
    location: LonLat


class NetworkPath(Model):
    routeId: str
    directionId: DirectionId
    polyline: str
    geometry: LineString | None = None  # additive: the decoded polyline, [lon, lat]


class Network(Model):
    feedVersion: str
    routes: list[NetworkRoute]
    stops: list[NetworkStop]
    paths: list[NetworkPath]
    provenance: list[Provenance] | None = None  # additive


class ZoneCollection(FeatureCollection):
    provenance: list[Provenance] | None = None  # additive foreign member


# --- closures -------------------------------------------------------------------


class RouteAction(Model):
    routeId: str
    directionId: DirectionId | None
    action: Literal["suspended", "shortened", "rerouted"]
    fromStopId: str | None = None
    toStopId: str | None = None
    keepStopIds: list[str] | None = None
    suspendedStopIds: list[str] | None = None
    stopNames: list[str] | None = None


class TemporaryRoute(Model):
    shortName: str
    mode: Literal["bus", "tram", "trolleybus"]
    streets: list[str]
    stopIds: list[str] | None = None
    geometry: LineString | None = None


class ClosureInput(Model):
    title: I18n
    kind: Literal["drawn", "notice"]
    geometry: LineGeometry | None
    bufferMeters: float = 30
    direction: Literal["both", "along", "against"] = "both"
    window: Window
    routeIds: list[str] | None = None
    sourceText: str | None = None
    sourceUrl: str | None = None
    routeActions: list[RouteAction] | None = None
    temporaryRoutes: list[TemporaryRoute] | None = None
    locationNote: I18n | None = None  # v2.3: e.g. „locație aproximativă: anunțul nu dă punctul exact”


class Closure(ClosureInput):
    id: str
    status: ClosureStatus
    createdAt: IsoTime


class ParseResult(Model):
    closure: Closure
    unread: list[str]


# --- analysis / impact ----------------------------------------------------------


class NearestServed(Model):
    stopId: str
    name: str
    location: LonLat
    distanceMeters: float | None
    routeIds: list[str]


class AffectedStop(Model):
    stopId: str
    name: str
    location: LonLat
    zoneSlug: str | None
    routeId: str
    routeShortName: str
    directionId: DirectionId
    headsign: str | None
    state: Literal["affected", "unsure"]
    confidence: float = Field(ge=0, le=1)
    reasons: list[ReasonCode]
    confirmed: bool | None
    departuresLost: int | None
    nearestServed: NearestServed | None


class AnalysisRoute(Model):
    routeId: str
    shortName: str
    type: int
    directionIds: list[DirectionId]
    stopsAffected: int


class Analysis(Model):
    closureId: str
    feedVersion: str
    stops: list[AffectedStop]
    routes: list[AnalysisRoute]
    unsureCount: int
    provenance: list[Provenance]


class StopDecision(Model):
    stopId: str
    routeId: str
    directionId: DirectionId
    confirmed: bool


class StopDecisions(Model):
    decisions: list[StopDecision]


class ImpactTotals(Model):
    stopsSuspended: int
    departuresLost: int | None  # v2.3: null when the window is outside every timetable we hold
    routesAffected: int
    residentsLosingStop: int | None
    stopRoutePairsLost: int | None = None  # v2.1


class ZoneImpact(Model):
    slug: str
    name: str
    stopsSuspended: int
    departuresLost: int | None  # v2.3: null with the totals
    residentsLosingStop: int | None
    maxExtraWalkMeters: float | None


class Impact(Model):
    closureId: str
    window: Window
    totals: ImpactTotals
    byZone: list[ZoneImpact]
    method: I18n
    provenance: list[Provenance]


class Compare(Model):
    a: Impact
    b: Impact


# --- alerts / publish -----------------------------------------------------------


class InformedEntity(Model):
    routeId: str | None = None
    stopId: str | None = None
    directionId: DirectionId | None = None


class Alert(Model):
    id: str
    closureId: str
    activePeriod: list[Window]
    cause: AlertCause
    effect: AlertEffect
    informedEntity: list[InformedEntity]
    headerText: I18n
    descriptionText: I18n
    url: str
    ttsHeaderText: I18n | None = None  # v2
    ttsDescriptionText: I18n | None = None  # v2


class Poster(Model):
    stopId: str
    url: str


class PublishResult(Model):
    closureId: str
    alerts: list[Alert]
    feedUrl: str
    posters: list[Poster]
    publishedAt: IsoTime


# --- live check -----------------------------------------------------------------


class LiveObservation(Model):
    vehicleId: str
    routeId: str
    tripId: str | None
    directionId: DirectionId | None
    stopId: str
    served: bool
    seenAt: IsoTime
    delaySec: int | None


class LiveSummary(Model):
    vehiclesSeen: int | None
    stopsSkipped: int | None
    stopsServedAnyway: int | None


class LiveCheck(Model):
    closureId: str
    from_: IsoTime = Field(alias="from")
    to: IsoTime
    source: Literal["live", "replay"]
    observations: list[LiveObservation]
    summary: LiveSummary
    provenance: list[Provenance]


# --- cases ----------------------------------------------------------------------


class CaseSummary(Model):
    id: str
    title: I18n
    kind: Literal["drawn", "notice"]
    date: IsoDate
    closureId: str
    note: I18n
