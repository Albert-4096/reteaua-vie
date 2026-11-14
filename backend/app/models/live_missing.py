"""CONTRACT v2.13 types of GET /api/live/missing (O2: lines with no vehicle in our live recording)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.models.service_confirmation import ServiceConfirmation
from app.travellers.models import TravellerSignal
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
    decision: TriageDecision | None = None   # v2.24 (R4): the latest decision of a person on this row
    repeatedDays: int | None = None          # v2.24 (R4): recorded days with the route in the same state, same hours
    travellerReports: TravellerSignal | None = None   # v2.35 (R20): riders said the bus did not come: a signal, unconfirmed
    serviceConfirmation: ServiceConfirmation | None = None   # v2.29 (C2): ≥ 2 phones checked in on the line while no vehicle is in the recording


Decision = Literal["confirmat", "respins", "nu_stiu"]
Reason = Literal["dispozitiv_bord", "linie_neoperata", "trafic_lucrari_vreme", "gol_date"]


class TriageInput(Model):
    """PATCH /api/live/missing/{routeId}: a person's decision on one row (R4)."""
    window: Window                  # the row's window, as /api/live/missing returned it
    decision: Decision              # „Confirm” | „Resping” | „Nu știu”
    reason: Reason | None = None    # null = „motiv necunoscut”
    who: str = Field(min_length=2, max_length=60)    # a role („dispecer STPT”), never a person's name
    note: str | None = Field(None, max_length=300)


class TriageDecision(Model):
    id: str
    routeId: str
    shortName: str | None
    window: Window
    caseId: str | None
    decision: Decision
    reason: Reason | None
    who: str
    note: str | None
    decidedAt: IsoTime
    rowState: RouteState            # the row as the person saw it
    tripsInService: int
    tripsObserved: int
    since: IsoTime


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
