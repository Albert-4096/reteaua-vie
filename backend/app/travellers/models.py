"""R20: fixed-category problem reports from the stop poster. A signal, never a fact; never sent to Sesizări."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.models.base import I18n, IsoTime, Model, Provenance

Category = Literal["closed_but_bus_came", "bus_did_not_come", "poster_wrong", "accessibility"]

CATEGORY_LABELS: dict[str, I18n] = {
    "closed_but_bus_came": I18n(ro="stația e anunțată închisă, dar autobuzul a venit", en="stop announced closed, but the bus came"),
    "bus_did_not_come": I18n(ro="autobuzul nu a venit", en="the bus did not come"),
    "poster_wrong": I18n(ro="afișul nu e corect", en="the poster is wrong"),
    "accessibility": I18n(ro="problemă de accesibilitate", en="accessibility problem"),
}


class ReportInput(Model):
    stopId: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,40}$")
    category: Category
    routeId: str | None = Field(None, pattern=r"^[A-Za-z0-9_.-]{1,40}$")     # optional: the line the rider means
    lat: float | None = Field(None, ge=-90, le=90)       # the position at that moment only, on a tap; both or none
    lon: float | None = Field(None, ge=-180, le=180)
    deviceKey: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class ReportAck(Model):
    stopId: str
    stopName: str | None
    category: Category
    label: I18n
    counted: bool                      # false when the same phone already reported this on this stop in the last 10 min
    note: I18n
    provenance: list[Provenance]


class CategoryCount(Model):
    category: Category
    label: I18n
    travellers: int                    # distinct phones (salted daily hash); counts only, no text
    reports: int


class StopReports(Model):
    stopId: str
    stopName: str | None
    travellers: int                    # distinct phones, any category
    byCategory: list[CategoryCount]


class ReportSummary(Model):
    window: dict
    stops: list[StopReports]
    travellers: int
    note: I18n
    provenance: list[Provenance]


class TravellerSignal(Model):
    """What S1 / O2 carry: „semnalat de N călători”. A signal from riders, not a finding."""
    travellers: int
    byCategory: dict[str, int]
    window: dict                       # {start, end}
    label: I18n
