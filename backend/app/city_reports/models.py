"""R26 + R19 response types (CONTRACT v2.19, v2.20): counts and ages only, never a report's text or point."""

from __future__ import annotations

from app.models.base import I18n, Model, Provenance, Window


class AreaRow(Model):
    id: str  # zone slug or stopId
    name: str
    total: int  # reports recorded in the area (any status)
    open: int  # status other than „Finalizata” and „Declinata competenta”, as of the last poll that held the report
    resolved: int  # status „Finalizata”
    resolvedShare: float | None  # resolved / total; null when total is 0
    oldestOpenAt: str | None  # createdAt of the oldest recorded open report; null when none
    distinctProblems: int  # same category within 25 m counts once
    departuresPerDay: int  # GTFS departures on a typical working day (stops in the zone, or at the stop)
    location: list[float] | None  # stops only: [lon, lat] of the stop


class AreaReports(Model):
    kind: str  # "zones" | "stops"
    categories: list[str]
    radiusMeters: int | None  # stops only
    departuresDay: str  # the working day the departures are counted on
    recorded: Window  # creation times our polls cover
    reportsRecorded: int  # unique reports in the recording that match the categories
    rows: list[AreaRow]
    label: I18n
    note: I18n
    provenance: list[Provenance]


class RoadSegment(Model):
    segmentId: str
    fromStopId: str
    fromName: str
    toStopId: str
    toName: str
    routeIds: list[str]
    potholes: int
    departuresPerDay: int
    lengthMeters: int


class RoadIssues(Model):
    label: I18n
    recorded: Window
    departuresDay: str
    potholesRecorded: int  # all „Groapă” reports in the recording
    potholesOnCorridors: int  # of them, within the match distance of a bus or trolleybus segment
    matchMeters: int
    segmentsWithReports: int
    segments: list[RoadSegment]  # top by departures per day
    provenance: list[Provenance]
