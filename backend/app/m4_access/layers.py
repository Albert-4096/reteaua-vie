"""M4 map layers: access destinations (OSM) and population (GHSL), as LayerCollection.

Destinations (SPEC §6.4), from $DATA_DIR/osm/timisoara.osm.pbf with pyrosm:
- hospital     = amenity=hospital mapped as a polygon (its centroid). Point-tagged
                 "hospitals" in this extract are clinics, labs and doctors' offices.
- school       = amenity=school
- rail_station = railway=station
Read once and cached as JSON in $DATA_DIR/cache, keyed by the pbf size and time.

Population: GHSL GHS-POP 2020, 3 arcsec (about 100 m) cells with residents > 0,
as polygons (the cell's pixel bounds), label „model GHSL 2020, 100 m (nu recensământ)”.

Public:
    load_destinations() -> list[Destination]
    destinations(kind) -> list[Destination]
    destinations_layer(bbox=None) -> dict (LayerCollection)
    population_cells() -> PopCells
    population_layer(bbox=None) -> dict (LayerCollection)
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.common import provenance as prov
from app.common.city import load_zones
from app.common.errors import unavailable
from app.config import get_settings
from app.m1_disruption import impact as imp
from app.models.base import Provenance

Bbox = tuple[float, float, float, float]

DEST_KINDS = ("hospital", "school", "rail_station")
DEST_CACHE_VERSION = 2
OSM_FILE = "osm/timisoara.osm.pbf"
POP_FILE = "pop/ghsl_2020_100m.tif"
GHSL_LABEL = imp.GHSL_LABEL

_lock = threading.Lock()


@dataclass(frozen=True)
class Destination:
    kind: str
    osmId: str            # "node/123", "way/456", "relation/789"
    name: str | None
    lon: float
    lat: float


# --- OSM destinations ------------------------------------------------------------------


def _pbf() -> Path:
    return get_settings().data_dir / OSM_FILE


def _dest_cache(pbf: Path) -> Path:
    st = pbf.stat()
    key = hashlib.sha1(f"{DEST_CACHE_VERSION}:{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()[:12]
    return get_settings().cache_dir / f"osm_destinations_v{DEST_CACHE_VERSION}_{key}.json"


def _osm_id(row) -> str:
    kind = str(getattr(row, "osm_type", "") or "node")
    return f"{kind}/{int(row.id)}"


def _name(row) -> str | None:
    """The `name` column, else `name` inside the raw OSM tags (pyrosm keeps unknown keys there)."""
    value = getattr(row, "name", None)
    if not (isinstance(value, str) and value.strip()):
        tags = getattr(row, "tags", None)
        try:
            value = json.loads(tags).get("name") if isinstance(tags, str) else (tags or {}).get("name")
        except (ValueError, AttributeError):
            value = None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _read_osm(pbf: Path) -> list[Destination]:
    import pyrosm  # noqa: PLC0415 - slow import, only when building the cache

    osm = pyrosm.OSM(str(pbf))
    out: list[Destination] = []
    pois = osm.get_pois(custom_filter={"amenity": ["hospital", "school"]})
    if pois is not None:
        for row in pois.itertuples(index=False):
            amenity = getattr(row, "amenity", None)
            if amenity not in ("hospital", "school") or row.geometry is None or row.geometry.is_empty:
                continue
            if amenity == "hospital" and row.geometry.geom_type not in ("Polygon", "MultiPolygon"):
                continue  # SPEC: hospital polygons only; the point-tagged ones here are clinics and labs
            c = row.geometry.centroid
            out.append(Destination(amenity, _osm_id(row), _name(row), c.x, c.y))
    rail = osm.get_data_by_custom_criteria(custom_filter={"railway": ["station"]}, filter_type="keep",
                                           keep_nodes=True, keep_ways=True, keep_relations=True)
    if rail is not None:
        for row in rail.itertuples(index=False):
            if getattr(row, "railway", None) != "station" or row.geometry is None or row.geometry.is_empty:
                continue
            c = row.geometry.centroid
            out.append(Destination("rail_station", _osm_id(row), _name(row), c.x, c.y))
    # one point per OSM object
    seen: set[tuple[str, str]] = set()
    uniq = []
    for d in out:
        if (d.kind, d.osmId) not in seen:
            seen.add((d.kind, d.osmId))
            uniq.append(d)
    return sorted(uniq, key=lambda d: (d.kind, d.name or "", d.osmId))


@lru_cache(maxsize=1)
def load_destinations() -> tuple[Destination, ...]:
    pbf = _pbf()
    if not pbf.is_file():
        raise unavailable(f"OSM extract missing: {OSM_FILE} (run `make data`).")
    cache = _dest_cache(pbf)
    with _lock:
        if cache.is_file():
            return tuple(Destination(**d) for d in json.loads(cache.read_text()))
        dests = _read_osm(pbf)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(d) for d in dests], ensure_ascii=False))
        tmp.replace(cache)
        return tuple(dests)


def destinations(kind: str) -> list[Destination]:
    return [d for d in load_destinations() if d.kind == kind]


def osm_provenance() -> Provenance:
    p = prov.from_sources("osm")
    if p is None:
        p = prov.for_file("OpenStreetMap", _pbf(), "https://www.openstreetmap.org")
    return p


def _in_bbox(lon: float, lat: float, bbox: Bbox | None) -> bool:
    return bbox is None or (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3])


def destinations_layer(bbox: Bbox | None = None) -> dict:
    """Hospitals, schools and rail stations from OSM, as points (LayerCollection `destinations`)."""
    feats = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(d.lon, 6), round(d.lat, 6)]},
        "properties": {"kind": d.kind, "osmId": d.osmId, "name": d.name},
    } for d in load_destinations() if _in_bbox(d.lon, d.lat, bbox)]
    p = osm_provenance()
    note = ("amenity=hospital (centroid), amenity=school, railway=station; "
            + (p.note or "")).strip("; ")
    return {"type": "FeatureCollection", "layer": "destinations", "features": feats,
            "provenance": [p.model_copy(update={"note": note}).model_dump()]}


# --- GHSL population ------------------------------------------------------------------------


@dataclass(frozen=True)
class PopCells:
    cell_id: np.ndarray       # str, "r<row>c<col>"
    lon: np.ndarray           # cell centre
    lat: np.ndarray
    residents: np.ndarray     # float (a model: fractions of people)
    zone: np.ndarray          # index into load_zones().slugs, -1 outside the 40 zones
    half_w: float             # half a pixel, degrees
    half_h: float


@lru_cache(maxsize=1)
def population_cells() -> PopCells:
    """Every GHSL cell with residents > 0 (same selection as m1 impact's grid)."""
    import rasterio  # noqa: PLC0415
    import shapely  # noqa: PLC0415

    path = get_settings().data_dir / POP_FILE
    if not path.is_file():
        raise unavailable(f"Population raster missing: {POP_FILE} (run `make data`).")
    with rasterio.open(path) as r:
        a = r.read(1).astype(float)
        nodata = r.nodata
        ok = np.isfinite(a) & (a > 0)
        if nodata is not None:
            ok &= a != nodata
        rows, cols = np.nonzero(ok)
        xs, ys = rasterio.transform.xy(r.transform, rows, cols, offset="center")
        half_w, half_h = abs(r.transform.a) / 2, abs(r.transform.e) / 2
    lon, lat = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    z = load_zones()
    zone = -np.ones(len(lon), dtype=np.int32)
    for i, shp in enumerate(z.shapes):
        inside = shapely.contains_xy(shp, lon, lat) & (zone < 0)
        zone[inside] = i
    ids = np.array([f"r{r_}c{c_}" for r_, c_ in zip(rows, cols)])
    return PopCells(ids, lon, lat, a[rows, cols], zone, half_w, half_h)


def pop_provenance() -> Provenance:
    return imp.pop_provenance()


def population_layer(bbox: Bbox | None = None) -> dict:
    """GHSL cells with residents as 100 m polygons (LayerCollection `population`)."""
    cells = population_cells()
    sel = np.ones(len(cells.lon), dtype=bool)
    if bbox is not None:
        sel = (cells.lon >= bbox[0]) & (cells.lon <= bbox[2]) & (cells.lat >= bbox[1]) & (cells.lat <= bbox[3])
    hw, hh = cells.half_w, cells.half_h
    feats = []
    for cid, x, y, res in zip(cells.cell_id[sel], cells.lon[sel], cells.lat[sel], cells.residents[sel]):
        x0, x1, y0, y1 = round(x - hw, 6), round(x + hw, 6), round(y - hh, 6), round(y + hh, 6)
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]},
            "properties": {"cellId": str(cid), "residents": round(float(res), 1)},
        })
    return {"type": "FeatureCollection", "layer": "population", "features": feats,
            "provenance": [pop_provenance().model_dump()]}

