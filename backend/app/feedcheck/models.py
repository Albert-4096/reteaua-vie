"""R21 response types (CONTRACT v2.12): GTFS version diff and the published-alert check."""

from __future__ import annotations

from typing import Literal

from app.models.base import I18n, Model, Provenance


class FeedVersionInfo(Model):
    version: str | None
    startDate: str | None
    endDate: str | None
    stops: int
    trips: int
    routes: int


class StopRef(Model):
    stopId: str
    name: str


class RouteRef(Model):
    routeId: str
    shortName: str


class RouteTripDelta(Model):
    routeId: str
    shortName: str
    added: int
    removed: int


class ServiceDayDelta(Model):
    date: str
    tripsBase: int
    tripsTarget: int


class FeedDiff(Model):
    base: FeedVersionInfo
    target: FeedVersionInfo
    stopsAdded: list[StopRef]
    stopsRemoved: list[StopRef]
    routesAdded: list[RouteRef]
    routesRemoved: list[RouteRef]
    tripsAdded: int
    tripsRemoved: int
    tripsByRoute: list[RouteTripDelta]
    tripsChanged: int  # trips in both whose stops or stop times differ (stop_sequence renumbering ignored)
    patternsAdded: int  # route + direction + stop pairs served only in the target
    patternsRemoved: int  # ... served only in the base
    serviceDays: list[ServiceDayDelta]  # only days that differ, among days both feeds cover
    daysCompared: int
    provenance: list[Provenance]


# not_served: calls in the base, none in the target. now_served: none in the base (the alert suspends it), calls in the target.
RowStatus = Literal["ok", "stop_missing", "route_missing", "not_served", "now_served", "renamed", "moved"]


class FeedCheckRow(Model):
    stopId: str
    name: str
    routeId: str
    directionId: int | None
    status: RowStatus
    tripsBase: int
    tripsTarget: int


class FeedCheck(Model):
    closureId: str
    base: FeedVersionInfo
    target: FeedVersionInfo
    takesEffectOn: str | None
    windowEnd: str | None
    applies: bool
    verdict: Literal["valid", "republish", "check", "not_applicable"]
    rows: list[FeedCheckRow]
    summary: I18n
    draftNotice: I18n | None
    diff: FeedDiff
    provenance: list[Provenance]
