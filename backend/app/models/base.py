"""Shared building blocks for the contract models (CONTRACT.md "Conventions")."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


class Model(BaseModel):
    """Base for every contract type: JSON names exactly as in CONTRACT.md."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _check_iso_offset(value: str) -> str:
    """ISO 8601 with an explicit offset (CONTRACT: times carry their offset)."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"time without offset: {value!r}")
    return value


IsoTime = Annotated[str, AfterValidator(_check_iso_offset)]
"""An ISO 8601 time string with offset, kept exactly as given."""


def _check_date(value: str) -> str:
    datetime.strptime(value, "%Y-%m-%d")
    return value


IsoDate = Annotated[str, AfterValidator(_check_date)]


def _check_lonlat(value: list[float]) -> list[float]:
    if len(value) < 2:
        raise ValueError("a position needs [lon, lat]")
    lon, lat = value[0], value[1]
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError(f"not a [lon, lat] position: {value}")
    return value


LonLat = Annotated[list[float], AfterValidator(_check_lonlat)]
"""A GeoJSON position, [lon, lat]."""


class I18n(Model):
    ro: str
    en: str | None = None


class Provenance(Model):
    source: str
    url: str | None
    version: str | None
    fetchedAt: IsoTime
    note: str | None


class Window(Model):
    start: IsoTime
    end: IsoTime


class ErrorDetail(Model):
    code: str
    message: str


class ErrorResponse(Model):
    error: ErrorDetail


# --- GeoJSON (RFC 7946, [lon, lat]) -----------------------------------------


class Point(Model):
    type: Literal["Point"]
    coordinates: LonLat


class LineString(Model):
    type: Literal["LineString"]
    coordinates: list[LonLat] = Field(min_length=2)


class MultiLineString(Model):
    type: Literal["MultiLineString"]
    coordinates: list[list[LonLat]]


class Polygon(Model):
    type: Literal["Polygon"]
    coordinates: list[list[LonLat]]


class MultiPolygon(Model):
    type: Literal["MultiPolygon"]
    coordinates: list[list[list[LonLat]]]


class MultiPoint(Model):
    type: Literal["MultiPoint"]
    coordinates: list[LonLat]


Geometry = Annotated[
    Union[Point, LineString, MultiLineString, Polygon, MultiPolygon, MultiPoint],
    Field(discriminator="type"),
]
LineGeometry = Annotated[Union[LineString, MultiLineString], Field(discriminator="type")]


class Feature(Model):
    type: Literal["Feature"]
    geometry: Geometry | None
    properties: dict[str, Any]


class FeatureCollection(Model):
    type: Literal["FeatureCollection"]
    features: list[Feature]
