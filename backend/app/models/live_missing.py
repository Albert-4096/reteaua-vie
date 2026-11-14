"""CONTRACT v2.13 types of GET /api/live/missing (O2: lines with no vehicle in our live recording)."""

from __future__ import annotations

from typing import Literal

from app.models.base import I18n, IsoTime, Model, Provenance, Window

MissingStatus = Literal["ok", "inregistrare_incompleta"]
RouteState = Literal["fara_vehicul", "partial"]
Mode = Literal["autobuz", "troleibuz", "tramvai"]


class MissedTrip(Model):
    tripId: str
    stopId: str | None
    stopName: str | None
    scheduledTime: IsoTime | None   # departure at stopId: the trip's first stop inside the window


class MissingRoute(Model):
    routeId: str
    shortName: str | None
    longName: str | None
    mode: Mode | None
    state: RouteState
    tripsInService: int             # scheduled trips whose span overlaps the window
    tripsObserved: int              # of those, seen in a healthy snapshot (tripId, or route + direction)
    since: IsoTime                  # fara_vehicul: first time in the window a trip was due; partial: first missed trip
    lastSeenAt: IsoTime | None      # last healthy snapshot in the window with a vehicle of the route
    firstMissedTrip: MissedTrip | None


class ModeCount(Model):
    mode: Mode
    tripsScheduled: int             # trips in service in the window
    tripsWithNoVehicle: int         # „curse fără vehicul în datele live”, never „curse neefectuate”
    share: float | None             # tripsWithNoVehicle / tripsScheduled, null when 0 scheduled


class RecordingHealth(Model):
    snapshots: int                  # snapshots in the window
    healthySnapshots: int           # realtimeAgeSec <= 120
    healthyShare: float             # minutes of the window with a healthy snapshot / minutes of the window
    files: list[str]                # recording files read


class CaseLabel(Model):
    id: str                         # "case_l23"
    label: I18n                     # „înregistrat 14 nov”


class MissingLines(Model):
    window: Window
    status: MissingStatus           # inregistrare_incompleta: healthy share < 80 %, nothing flagged
    case: CaseLabel | None          # set for a prepared case, null for a live window
    recording: RecordingHealth
    routes: list[MissingRoute]
    byMode: list[ModeCount]
    provenance: list[Provenance]


class MissingBrief(Model):
    """The step 0 („Ansamblu”) slice of MissingLines, inside Overview."""
    window: Window
    status: MissingStatus
    case: CaseLabel | None
    count: int                      # routes fara_vehicul
    partialCount: int               # routes partial
    rows: list[MissingRoute]        # the top rows (fara_vehicul first)


class MissingOverview(Model):
    live: MissingBrief | None       # the last 60 min of the real clock; null if the detector failed
    prepared: MissingBrief | None   # case_l23, so step 0 works at any hour
