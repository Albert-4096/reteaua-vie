"""Cached loaders for the city files in $DATA_DIR/city-api-2026-11-13/.

All outputs are GeoJSON order [lon, lat]. The city's network file gives stops
as separate `lat` / `lon` fields; we keep those (same shape as the city API)
and add `location: [lon, lat]`. Path polylines (precision 5) are decoded to
LineStrings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from shapely import STRtree
from shapely.geometry import LineString, Point, shape
from shapely.geometry.base import BaseGeometry

from app.common import provenance as prov
from app.common.errors import unavailable
from app.common.geo import decode_polyline, project_lonlats
from app.config import get_settings
from app.models.base import Provenance

NETWORK_FILE = "transit-network.json"
ZONES_FILE = "zones.geojson"
PARKING_FILE = "parking.json"
POIS_FILE = "pois.json"

ROUTE_MODES = {0: "tram", 3: "bus", 11: "trolleybus", 800: "trolleybus"}


def _city_file(name: str) -> Path:
    path = get_settings().city_dir / name
    if not path.is_file():
        raise unavailable(f"Data file missing: {name} (run `make data`).")
    return path


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def route_mode(route_id: str, route_type: int | None = None) -> str:
    """tram / bus / trolleybus from the city id prefix (R_TV_, R_AB_, R_TB_)."""
    if route_id.startswith("R_TV_"):
        return "tram"
    if route_id.startswith("R_TB_"):
        return "trolleybus"
    if route_id.startswith("R_AB_"):
        return "bus"
    return ROUTE_MODES.get(route_type or 3, "bus")


# --- network -------------------------------------------------------------------


@dataclass(frozen=True)
class NetworkData:
    feed_version: str
    routes: list[dict]                      # as the city serves them
    stops: list[dict]                       # + "location": [lon, lat]
    paths: list[dict]                       # + "geometry": GeoJSON LineString
    route_by_id: dict[str, dict]
    stop_by_id: dict[str, dict]
    path_lines: dict[tuple[str, int], LineString]   # (routeId, directionId) -> WGS84 line
    stop_ids: list[str]                     # order of stop_xy rows
    stop_xy: np.ndarray                     # (N, 2) UTM 34N metres
    provenance: Provenance


@lru_cache(maxsize=1)
def load_network() -> NetworkData:
    path = _city_file(NETWORK_FILE)
    raw = _read_json(path)
    stops = []
    for s in raw["stops"]:
        s2 = dict(s)
        s2["id"] = str(s["id"])
        s2["location"] = [float(s["lon"]), float(s["lat"])]
        stops.append(s2)
    paths = []
    lines: dict[tuple[str, int], LineString] = {}
    for p in raw["paths"]:
        coords = decode_polyline(p["polyline"])
        p2 = dict(p)
        p2["geometry"] = {"type": "LineString", "coordinates": coords}
        paths.append(p2)
        if len(coords) >= 2:
            lines[(p["routeId"], int(p["directionId"]))] = LineString(coords)
    version = raw.get("feedVersion")
    return NetworkData(
        feed_version=version,
        routes=raw["routes"],
        stops=stops,
        paths=paths,
        route_by_id={r["id"]: r for r in raw["routes"]},
        stop_by_id={s["id"]: s for s in stops},
        path_lines=lines,
        stop_ids=[s["id"] for s in stops],
        stop_xy=project_lonlats((s["location"][0], s["location"][1]) for s in stops),
        provenance=prov.network_provenance(path, version),
    )


def network_payload() -> dict:
    """GET /api/network body: the city shape + stop `location` + path `geometry`."""
    n = load_network()
    return {
        "feedVersion": n.feed_version,
        "routes": n.routes,
        "stops": n.stops,
        "paths": n.paths,
        "provenance": [n.provenance.model_dump()],
    }


# --- zones ----------------------------------------------------------------------


@dataclass(frozen=True)
class ZonesData:
    collection: dict                        # GeoJSON FeatureCollection as served
    slugs: list[str]
    names: dict[str, str]                   # slug -> name
    shapes: list[BaseGeometry]              # same order as slugs, WGS84
    tree: STRtree
    provenance: Provenance


@dataclass(frozen=True)
class Landmark:
    id: str
    name: str            # exactly as the City Hall gives it
    nameEn: str | None
    address: str | None
    lon: float
    lat: float


def load_landmarks() -> tuple[tuple[Landmark, ...], Provenance] | None:
    """The City Hall's tourist-guide landmarks (/api/mobile/pois, fetched once, read from disk).

    None when the file is not on disk (R28 then leaves the landmark destinations out).
    """
    path = get_settings().city_dir / POIS_FILE
    if not path.is_file():
        return None
    sig = (str(path), path.stat().st_mtime)
    return _landmarks(*sig)


@lru_cache(maxsize=2)
def _landmarks(path_str: str, _mtime: float) -> tuple[tuple[Landmark, ...], Provenance]:
    path = Path(path_str)
    rows = _read_json(path).get("pois", [])
    items = tuple(Landmark(id=str(p["id"]), name=p["name"], nameEn=p.get("nameEn") or None, address=p.get("address") or None,
                           lon=float(p["longitude"]), lat=float(p["latitude"])) for p in rows)
    return items, prov.pois_provenance(path)


@lru_cache(maxsize=1)
def load_zones() -> ZonesData:
    path = _city_file(ZONES_FILE)
    raw = _read_json(path)
    feats = []
    slugs, shapes = [], []
    names = {}
    for f in raw["features"]:
        props = f.get("properties") or {}
        slug, name = props.get("slug"), props.get("name")
        # keep only type + coordinates (the city adds a legacy `crs` member; order is [lon, lat])
        geom = {"type": f["geometry"]["type"], "coordinates": f["geometry"]["coordinates"]}
        feats.append({"type": "Feature", "geometry": geom,
                      "properties": {"slug": slug, "name": name, "id": props.get("id")}})
        slugs.append(slug)
        names[slug] = name
        shapes.append(shape(geom))
    return ZonesData(
        collection={"type": "FeatureCollection", "features": feats},
        slugs=slugs,
        names=names,
        shapes=shapes,
        tree=STRtree(shapes),
        provenance=prov.zones_provenance(path),
    )


def zone_for_point(lon: float, lat: float) -> str | None:
    """Slug of the neighbourhood containing the point, or None outside all 40."""
    z = load_zones()
    pt = Point(lon, lat)
    for i in z.tree.query(pt, predicate="intersects"):
        return z.slugs[int(i)]
    return None


def zones_for_geometry(geom: BaseGeometry) -> list[str]:
    z = load_zones()
    return [z.slugs[int(i)] for i in z.tree.query(geom, predicate="intersects")]


# --- parking ----------------------------------------------------------------------


@dataclass(frozen=True)
class ParkingData:
    version: str | None
    features: list[dict]                    # GeoJSON Features, props {kind, id, name, tariff}
    tariffs: dict
    provenance: Provenance


def _parking_geometry(kind: str, coords: list[list[float]]) -> dict:
    if kind in ("zone", "lot") and len(coords) >= 4 and coords[0] == coords[-1]:
        return {"type": "Polygon", "coordinates": [coords]}
    if len(coords) >= 2:
        return {"type": "LineString", "coordinates": coords}
    return {"type": "Point", "coordinates": coords[0]}


@lru_cache(maxsize=1)
def load_parking() -> ParkingData:
    path = _city_file(PARKING_FILE)
    raw = _read_json(path)
    feats = []
    for f in raw["features"]:
        coords = [[float(c[0]), float(c[1])] for c in f["coordinates"]]
        feats.append({
            "type": "Feature",
            "geometry": _parking_geometry(f["kind"], coords),
            "properties": {"kind": f["kind"], "id": f["id"], "name": f.get("name") or "",
                           "tariff": f.get("tariff") or ""},
        })
    version = str(raw.get("version")) if raw.get("version") is not None else None
    return ParkingData(version=version, features=feats, tariffs=raw.get("tariffs") or {},
                       provenance=prov.parking_provenance(path, version))


def parking_layer(bbox: tuple[float, float, float, float] | None = None) -> dict:
    """LayerCollection for /api/layers/parking, optionally clipped to a bbox."""
    p = load_parking()
    feats = p.features
    if bbox is not None:
        from shapely.geometry import box

        b = box(*bbox)
        feats = [f for f in feats if shape(f["geometry"]).intersects(b)]
    return {"type": "FeatureCollection", "layer": "parking", "features": feats,
            "provenance": [p.provenance.model_dump()]}


def clear_caches() -> None:
    load_network.cache_clear()
    load_zones.cache_clear()
    _landmarks.cache_clear()
    load_parking.cache_clear()
