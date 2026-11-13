"""Named OSM highway ways with their original names (for notices and P&R).

The M1 parser keeps only normalised names of the drive network. Neighbourhood
notices need the name as written (with diacritics) and also pedestrian ways
(squares such as Piața Victoriei), so this module reads every named
`highway=*` way from $DATA_DIR/osm/timisoara.osm.pbf once with pyrosm and
caches the result in $DATA_DIR/cache (keyed by the pbf size and mtime).

Public:
    named_ways() -> NamedWays          all named ways, WGS84 + metric, STRtree
    ways_in(area_wgs84, classes) -> list[int]
    place_point(name) -> Point | None  centroid of the ways with exactly this name
"""

from __future__ import annotations

import hashlib
import logging
import pickle
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from shapely import STRtree
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from app.common.geo import to_metric, to_wgs84
from app.config import get_settings

log = logging.getLogger("reteaua_vie.m3")

CACHE_VERSION = 1
OSM_FILE = "osm/timisoara.osm.pbf"

# Ways a resident reads as "a street" (no footpaths, tracks, planned or unbuilt roads).
STREET_CLASSES = frozenset({
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
    "living_street", "pedestrian", "service", "road",
    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
})


@dataclass
class NamedWays:
    osm_ids: list[str]
    names: list[str]                 # as written in OSM
    classes: list[str]               # highway=*
    lines_m: list[BaseGeometry]      # UTM 34N metres
    tree: STRtree                    # over lines_m
    source: str                      # pbf file name


def _pbf() -> Path:
    return get_settings().data_dir / OSM_FILE


def _build(pbf: Path) -> dict:
    import pyrosm  # slow import, only when building the cache

    osm = pyrosm.OSM(str(pbf))
    gdf = osm.get_data_by_custom_criteria(custom_filter={"highway": True}, filter_type="keep",
                                          keep_nodes=False, keep_relations=False)
    gdf = gdf[gdf["name"].notna()]
    ids, names, classes, wkb = [], [], [], []
    for osm_id, name, hw, geom in zip(gdf["id"], gdf["name"], gdf["highway"], gdf.geometry):
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type == "Polygon":
            geom = geom.exterior
        if geom.geom_type not in ("LineString", "LinearRing", "MultiLineString"):
            continue
        ids.append(str(int(osm_id)))
        names.append(str(name).strip())
        classes.append(str(hw))
        wkb.append(LineString(geom.coords).wkb if geom.geom_type != "MultiLineString" else geom.wkb)
    return {"ids": ids, "names": names, "classes": classes, "wkb": wkb}


def _load_raw() -> dict:
    pbf = _pbf()
    if not pbf.is_file():
        raise FileNotFoundError(f"OSM extract missing: {pbf} (run `make data`)")
    st = pbf.stat()
    key = hashlib.sha1(f"{CACHE_VERSION}:{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()[:12]
    cache = get_settings().cache_dir / f"osm_named_ways_v{CACHE_VERSION}_{key}.pkl"
    if cache.is_file():
        try:
            return pickle.loads(cache.read_bytes())
        except Exception:  # a broken cache file is rebuilt
            log.warning("rebuilding broken cache %s", cache.name)
    raw = _build(pbf)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(f".{np.random.randint(1 << 30)}.tmp")
    tmp.write_bytes(pickle.dumps(raw, protocol=pickle.HIGHEST_PROTOCOL))
    tmp.replace(cache)
    return raw


@lru_cache(maxsize=1)
def named_ways() -> NamedWays:
    import shapely

    raw = _load_raw()
    lines_wgs = [shapely.from_wkb(b) for b in raw["wkb"]]
    lines_m = [to_metric(g) for g in lines_wgs]
    return NamedWays(osm_ids=raw["ids"], names=raw["names"], classes=raw["classes"], lines_m=lines_m,
                     tree=STRtree(lines_m), source=_pbf().name)


def ways_in(area_wgs84: BaseGeometry, classes: frozenset[str] | None = STREET_CLASSES) -> list[int]:
    """Indices of named ways that intersect a WGS84 area (optionally only some highway classes)."""
    w = named_ways()
    area_m = to_metric(area_wgs84)
    out = []
    for i in w.tree.query(area_m, predicate="intersects"):
        i = int(i)
        if classes is None or w.classes[i] in classes:
            out.append(i)
    return sorted(out)


@lru_cache(maxsize=32)
def place_point(name: str) -> Point | None:
    """WGS84 centroid of all ways named exactly `name` (e.g. a square), or None."""
    w = named_ways()
    parts = [w.lines_m[i] for i, n in enumerate(w.names) if n == name]
    if not parts:
        return None
    return to_wgs84(unary_union(parts).centroid)


def clear_caches() -> None:
    named_ways.cache_clear()
    place_point.cache_clear()
