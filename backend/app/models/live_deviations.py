"""CONTRACT v2.29 types of GET /api/live/deviations (R18: off-route runs, with or without a notice)."""

from __future__ import annotations

from typing import Literal

from app.models.base import I18n, IsoTime, LonLat, Model, Provenance, Window
from app.models.delay_effect import DelayEffect

Classification = Literal["anuntata", "fara_anunt"]


class DeviationNotice(Model):
    postId: int | None
    url: str | None
    title: str | None


class DeviationTrack(Model):
    tripId: str
    vehicleId: str
    start: IsoTime
    end: IsoTime
    reports: int                   # consecutive fresh positions off the shape
    maxDistanceM: int              # farthest position from the trip's GTFS shape
    extraKm: float                 # track length minus the shape length it replaces (>= 0)
    coordinates: list[LonLat]      # the off-route positions, in time order


class DeviationGroup(Model):
    routeId: str
    shortName: str | None
    mode: Literal["autobuz", "troleibuz", "tramvai"] | None
    directionId: int | None
    street: str | None             # the named street most of the off-route positions are nearest to (OSM)
    nearStop: str | None           # the GTFS stop nearest to the middle of the first track
    classification: Classification
    label: I18n                    # „abatere de la traseu fără anunț găsit de noi — de verificat” / „anunțată …”
    closureId: str | None          # a published closure that explains it
    notice: DeviationNotice | None # or the STPT notice that names the line and the street
    runs: int
    trips: int                     # distinct trips with a run here
    tripsSeen: int                 # distinct trips of the route and direction in the recording window
    share: float | None            # trips / tripsSeen
    firstAt: IsoTime
    lastAt: IsoTime
    maxDistanceM: int
    extraKm: float                 # sum over the tracks; km, never lei
    tracks: list[DeviationTrack]
    delayEffect: DelayEffect | None = None   # v2.37 (R25): the delay the run adds, measured from L0


class DeviationCounts(Model):
    runs: int                      # every run of >= minReports fresh positions > offRouteMeters
    ignoredGpsLoss: int            # runs followed by >= gpsLossMinutes with no fresh position (extrapolated)
    ignoredOffSchedule: int        # runs outside the reported trip's time (positioning, layover, wrong trip id)
    ignoredStanding: int           # a vehicle standing off the line (layover)
    ignoredTerminal: int           # runs near the first or last point of the shape (turning loops)
    ignoredDepot: int              # runs near a garage stop
    kept: int
    announced: int                 # kept runs in an „anunțată” group
    unannounced: int


class DeviationThresholds(Model):
    offRouteMeters: int            # X
    minReports: int                # Y (consecutive fresh positions)
    terminalMeters: int
    depotMeters: int
    maxReportAgeSec: int
    beforeTripMinutes: int
    afterTripMinutes: int
    standingMinutes: int
    standingMetresPerSecond: float
    gpsLossMinutes: int


class Deviations(Model):
    window: Window
    status: Literal["ok", "inregistrare_incompleta"]
    thresholds: DeviationThresholds
    reports: int                   # fresh vehicle positions read
    counts: DeviationCounts
    groups: list[DeviationGroup]
    provenance: list[Provenance]
