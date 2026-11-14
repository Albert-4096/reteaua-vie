"""CONTRACT v2.18 types of GET /api/lines/status (R2: one state per line, for CityApp and Timi)."""

from __future__ import annotations

from typing import Literal

from app.models.service_confirmation import ServiceConfirmation
from app.models.base import I18n, IsoTime, Model, Provenance

LineState = Literal["normala", "deviata", "scurtata", "suspendata", "linie_temporara", "fara_vehicul"]


class LineNotice(Model):
    postId: int | None          # the STPT post id (stpt.ro), null when the closure's URL is not a saved post
    url: str | None
    title: str | None


class LineStatus(Model):
    routeId: str | None         # GTFS route_id; null for a line that exists only during a closure (4b)
    shortName: str | None
    mode: Literal["autobuz", "troleibuz", "tramvai"] | None
    state: LineState
    label: I18n                 # „suspendată”, „scurtată”, ...
    directionIds: list[int] | None   # the directions the state applies to; null = the whole line
    since: IsoTime | None       # the closure window; null for „normală”
    until: IsoTime | None
    closureId: str | None
    closureTitle: I18n | None
    notice: LineNotice | None
    replacedBy: list[str]       # short names of the closure's temporary lines that stand in for it (4 -> 4b)
    source: str                 # where the state comes from, in words
    serviceConfirmation: ServiceConfirmation | None = None   # v2.29 (C2): phones checked in in the last 30 min, no vehicle in the recording
    previousState: LineState | None = None   # set only in a ?since= answer: the state at `since`


class LinesStatus(Model):
    at: IsoTime
    since: IsoTime | None       # set for a changes-only answer
    lines: list[LineStatus]
    provenance: list[Provenance]
