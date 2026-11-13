"""The OSM bike network of the extract, read once with pyrosm and cached in $DATA_DIR/cache.

    bike_data() -> BikeData    segments (for routing), ways (LTS, infrastructure flag), bike
                               parking and share stations; all WGS84 [lon, lat] + UTM metres
"""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from shapely import STRtree
from shapely.geometry import LineString

from app.common.geo import project_lonlats
from app.config import get_settings
from app.m5_bike.lts import in_network, is_bike_way, lts

log = logging.getLogger(__name__)

CACHE_VERSION = 2
OSM_FILE = "osm/timisoara.osm.pbf"
TAG_COLUMNS = ("highway", "bicycle", "cycleway", "cycleway:left", "cycleway:right", "cycleway:both",
               "maxspeed", "oneway", "oneway:bicycle", "junction")


@dataclass
class BikeData:
    # segments (between OSM nodes), for routing
    seg_u: np.ndarray
    seg_v: np.ndarray
    seg_len: np.ndarray
    seg_way: np.ndarray                 # index into way_*
    seg_oneway: np.ndarray              # 0 both, 1 u->v, -1 v->u (for bicycles)
    seg_coords: list[np.ndarray]        # WGS84 per segment, u -> v
    seg_xy: list[np.ndarray]            # UTM 34N per segment
    # ways
    way_id: np.ndarray                  # OSM way id
    way_name: list[str | None]
    way_highway: list[str]
    way_lts: list[int | None]
    way_bike: np.ndarray                # bool: bike infrastructure ('lane' feature)
    way_ride: np.ndarray                # bool: a cyclist may ride it (routing)
    # points: bike parking and share stations
    poi_kind: list[str]                 # "parking" | "share_station"
    poi_osm: list[str]                  # "node/123" | "way/123"
    poi_name: list[str | None]
    poi_capacity: list[int | None]
    poi_lonlat: np.ndarray              # (N, 2)
    pbf_name: str = ""
    _trees: dict = field(default_factory=dict, repr=False)

    def seg_tree(self) -> STRtree:
        if "seg" not in self._trees:
            self._trees["seg"] = STRtree([LineString(x) for x in self.seg_xy])
        return self._trees["seg"]


def _pbf() -> Path:
    return get_settings().data_dir / OSM_FILE


def _tag(row, col) -> str | None:
    v = row.get(col)
    return v if isinstance(v, str) and v.strip() else None


def _oneway(tags: dict) -> int:
    if (tags.get("oneway:bicycle") or "").lower() == "no":
        return 0
    v = (tags.get("oneway") or "").lower()
    if v in ("yes", "true", "1"):
        return 1
    if v == "-1":
        return -1
    if v in ("no", "false", "0"):
        return 0
    return 1 if (tags.get("junction") or "") in ("roundabout", "circular") else 0


def _capacity(tags_raw) -> int | None:
    tags = tags_raw
    if isinstance(tags_raw, str):
        try:
            tags = json.loads(tags_raw)
        except ValueError:
            return None
    if not isinstance(tags, dict):
        return None
    try:
        return int(str(tags.get("capacity", "")).strip())
    except ValueError:
        return None


def _build(pbf: Path) -> BikeData:
    from pyrosm import OSM  # slow import, only when building

    osm = OSM(str(pbf))
    _nodes, edges = osm.get_network(network_type="cycling", nodes=True,
                                    extra_attributes=["cycleway:left", "cycleway:right", "cycleway:both",
                                                      "oneway:bicycle"])
    cols = [c for c in TAG_COLUMNS if c in edges.columns]
    way_pos: dict[int, int] = {}
    way_id, way_name, way_hw, way_lts, way_bike, way_ride = [], [], [], [], [], []
    seg_way, seg_oneway = [], []
    for rec in edges[["id", "name", *cols]].to_dict("records"):
        wid = int(rec["id"])
        tags = {c: _tag(rec, c) for c in cols}
        if wid not in way_pos:
            way_pos[wid] = len(way_id)
            way_id.append(wid)
            way_name.append(_tag(rec, "name"))
            way_hw.append(tags.get("highway") or "")
            way_lts.append(lts(tags))
            way_bike.append(is_bike_way(tags))
            way_ride.append(in_network(tags))
        seg_way.append(way_pos[wid])
        seg_oneway.append(_oneway(tags))
    coords = [np.asarray(g.coords, dtype=float)[:, :2] for g in edges.geometry]
    xy = [project_lonlats(map(tuple, c)) for c in coords]

    pois = osm.get_data_by_custom_criteria(custom_filter={"amenity": ["bicycle_parking", "bicycle_rental"]},
                                           filter_type="keep")
    kinds, osm_ids, names, caps, pts = [], [], [], [], []
    if pois is not None:
        for rec in pois.to_dict("records"):
            g = rec["geometry"]
            if g is None or g.is_empty:
                continue
            c = g if g.geom_type == "Point" else g.centroid
            kinds.append("parking" if rec.get("amenity") == "bicycle_parking" else "share_station")
            osm_ids.append(f"{rec.get('osm_type') or 'node'}/{int(rec['id'])}")
            names.append(_tag(rec, "name"))
            caps.append(_capacity(rec.get("tags")))
            pts.append((float(c.x), float(c.y)))
    return BikeData(
        seg_u=edges["u"].to_numpy(dtype=np.int64), seg_v=edges["v"].to_numpy(dtype=np.int64),
        seg_len=edges["length"].to_numpy(dtype=float), seg_way=np.asarray(seg_way, dtype=np.int64),
        seg_oneway=np.asarray(seg_oneway, dtype=np.int8), seg_coords=coords, seg_xy=xy,
        way_id=np.asarray(way_id, dtype=np.int64), way_name=way_name, way_highway=way_hw, way_lts=way_lts,
        way_bike=np.asarray(way_bike, dtype=bool), way_ride=np.asarray(way_ride, dtype=bool),
        poi_kind=kinds, poi_osm=osm_ids, poi_name=names, poi_capacity=caps,
        poi_lonlat=np.asarray(pts, dtype=float).reshape(-1, 2),
    )


_lock = threading.Lock()


@lru_cache(maxsize=1)
def bike_data() -> BikeData:
    pbf = _pbf()
    if not pbf.is_file():
        raise FileNotFoundError(f"OSM extract missing: {pbf} (run `make data`)")
    st = pbf.stat()
    key = hashlib.sha1(f"{CACHE_VERSION}:{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()[:12]
    cache = get_settings().cache_dir / f"bike_osm_v{CACHE_VERSION}_{key}.pkl"
    with _lock:
        data = None
        if cache.is_file():
            try:
                data = pickle.loads(cache.read_bytes())
            except Exception:
                log.warning("bike OSM cache unreadable, rebuilding")
        if data is None:
            data = _build(pbf)
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".tmp")
            tmp.write_bytes(pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL))
            tmp.replace(cache)
        data.pbf_name = pbf.name
        data._trees = {}
        return data
