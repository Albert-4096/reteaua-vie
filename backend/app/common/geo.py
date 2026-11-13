"""Small geo helpers for Timișoara.

Inputs and outputs are WGS84 [lon, lat] (GeoJSON order). Metric work uses
UTM zone 34N (EPSG:32634), which covers Timișoara (21.2°E) with low distortion.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any, Iterable

import numpy as np
import polyline as _polyline
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, Point, mapping, shape
from shapely.geometry.base import BaseGeometry

METRIC_CRS = "EPSG:32634"
EARTH_RADIUS_M = 6_371_008.8


@lru_cache(maxsize=1)
def _fwd() -> Transformer:
    return Transformer.from_crs("EPSG:4326", METRIC_CRS, always_xy=True)


@lru_cache(maxsize=1)
def _inv() -> Transformer:
    return Transformer.from_crs(METRIC_CRS, "EPSG:4326", always_xy=True)


def _apply(t: Transformer, coords: np.ndarray) -> np.ndarray:
    x, y = t.transform(coords[:, 0], coords[:, 1])
    return np.column_stack([x, y])


def to_metric(geom: BaseGeometry) -> BaseGeometry:
    """WGS84 [lon, lat] geometry -> UTM 34N metres."""
    return shapely.transform(geom, lambda c: _apply(_fwd(), c))


def to_wgs84(geom: BaseGeometry) -> BaseGeometry:
    """UTM 34N metres -> WGS84 [lon, lat]."""
    return shapely.transform(geom, lambda c: _apply(_inv(), c))


def lonlat_to_xy(lon: float, lat: float) -> tuple[float, float]:
    return _fwd().transform(lon, lat)


def xy_to_lonlat(x: float, y: float) -> tuple[float, float]:
    return _inv().transform(x, y)


def buffer_m(geom: BaseGeometry, meters: float) -> BaseGeometry:
    """Buffer a WGS84 geometry by metres; returns WGS84."""
    return to_wgs84(to_metric(geom).buffer(meters))


def distance_m(a: BaseGeometry, b: BaseGeometry) -> float:
    """Shortest distance in metres between two WGS84 geometries."""
    return float(to_metric(a).distance(to_metric(b)))


def length_m(geom: BaseGeometry) -> float:
    return float(to_metric(geom).length)


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bearing_deg(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Initial bearing from point 1 to point 2, degrees clockwise from north, 0..360."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def bearing_cos(b1: float, b2: float) -> float:
    """Cosine of the angle between two bearings: 1 same way, -1 opposite."""
    return math.cos(math.radians(b1 - b2))


def line_bearing_at(line: LineString, point: Point, step_m: float = 10.0) -> float:
    """Bearing of a WGS84 line at the location closest to `point` (along its order)."""
    ml = to_metric(line)
    mp = to_metric(point)
    d = ml.project(mp)
    d0 = max(0.0, d - step_m)
    d1 = min(ml.length, d + step_m)
    if d1 - d0 < 1e-6:
        coords = list(line.coords)
        return bearing_deg(*coords[0][:2], *coords[-1][:2])
    a = ml.interpolate(d0)
    b = ml.interpolate(d1)
    lon_a, lat_a = xy_to_lonlat(a.x, a.y)
    lon_b, lat_b = xy_to_lonlat(b.x, b.y)
    return bearing_deg(lon_a, lat_a, lon_b, lat_b)


def decode_polyline(encoded: str, precision: int = 5) -> list[list[float]]:
    """Google encoded polyline -> GeoJSON positions [[lon, lat], ...]."""
    return [[lon, lat] for lat, lon in _polyline.decode(encoded, precision)]


def to_geojson(geom: BaseGeometry) -> dict[str, Any]:
    """Shapely -> GeoJSON dict with plain lists (rounded to ~1 cm)."""
    def _round(c: Any) -> Any:
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
            return [round(float(v), 7) for v in c[:2]]
        return [_round(x) for x in c]

    g = mapping(geom)
    return {"type": g["type"], "coordinates": _round(g["coordinates"])}


def from_geojson(obj: dict[str, Any] | Any) -> BaseGeometry:
    """GeoJSON dict (or a pydantic geometry model) -> shapely geometry."""
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()
    return shape(obj)


def nearest(points_xy: np.ndarray, x: float, y: float, k: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Indices and distances (metres) of the k nearest metric points to (x, y)."""
    d = np.hypot(points_xy[:, 0] - x, points_xy[:, 1] - y)
    k = min(k, len(d))
    idx = np.argpartition(d, k - 1)[:k] if k < len(d) else np.arange(len(d))
    idx = idx[np.argsort(d[idx])]
    return idx, d[idx]


def project_lonlats(lonlats: Iterable[tuple[float, float]]) -> np.ndarray:
    """Many [lon, lat] -> (N, 2) metric array."""
    arr = np.asarray(list(lonlats), dtype=float)
    if arr.size == 0:
        return np.zeros((0, 2))
    return _apply(_fwd(), arr)
