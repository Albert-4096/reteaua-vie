"""R10: can one lane stay open for the bus through the works? Judged only from what OSM and the GTFS say.

For the street(s) a closure runs along (OSM driving ways whose clipped length inside the closure
buffer is at least 30 % of the closure length, else the longest one): `lanes` and `width` as tagged.
- one-way: enough with lanes >= 2 (one for the works, one kept); two-way: lanes >= 3.
- no `lanes`: lanes = floor(width / 3 m) when `width` is tagged (our convention, not a norm).
- neither tag: `enough` is null, we do not guess.
A closure that runs along a GTFS tram shape (tram shape within 10 m along at least half of it)
is not judged either: the tracks are the works.
The OSM driving network is read once with pyrosm and cached as a pickle in $DATA_DIR/cache.
"""

from __future__ import annotations

import hashlib
import pickle
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from shapely import STRtree
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from app.common import gtfs
from app.common.geo import from_geojson, project_lonlats, to_metric
from app.config import get_settings
from app.models.base import I18n

OSM_FILE = "osm/timisoara.osm.pbf"
CACHE_VERSION = 1
LANE_WIDTH_M = 3.0
MIN_SHARE = 0.3
TRAM_NEAR_M = 10.0
STREETS = frozenset({"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
                     "living_street", "road", "primary_link", "secondary_link", "tertiary_link"})
_lock = threading.Lock()


@dataclass
class Way:
    osm_id: str
    name: str | None
    highway: str
    lanes: int | None
    width: float | None
    oneway: bool
    geom: BaseGeometry   # UTM 34N


@dataclass
class StreetJudgement:
    osm_id: str
    name: str | None
    lanes: int | None
    width: float | None
    oneway: bool
    enough: bool | None


def _num(v) -> float | None:
    if v is None:
        return None
    m = re.match(r"\s*(\d+(?:[.,]\d+)?)", str(v))
    return float(m.group(1).replace(",", ".")) if m else None


def _read(pbf: Path) -> list[Way]:
    from pyrosm import OSM  # slow import, only when building the cache

    _n, edges = OSM(str(pbf)).get_network(network_type="driving", nodes=True, extra_attributes=["lanes", "width"])
    out: dict[int, Way] = {}
    for rec in edges.to_dict("records"):
        hw = rec.get("highway")
        if hw not in STREETS:
            continue
        wid = int(rec["id"])
        xy = project_lonlats([tuple(p) for p in rec["geometry"].coords])
        seg = LineString(xy)
        if wid in out:
            out[wid].geom = out[wid].geom.union(seg)
            continue
        lanes = _num(rec.get("lanes"))
        out[wid] = Way(osm_id=f"way/{wid}", name=rec.get("name") if isinstance(rec.get("name"), str) else None,
                       highway=hw, lanes=int(lanes) if lanes is not None else None, width=_num(rec.get("width")),
                       oneway=str(rec.get("oneway") or "").lower() in ("yes", "true", "1", "-1"), geom=seg)
    return list(out.values())


@lru_cache(maxsize=1)
def ways() -> tuple[tuple[Way, ...], STRtree]:
    pbf = get_settings().data_dir / OSM_FILE
    st = pbf.stat()
    key = hashlib.sha1(f"{CACHE_VERSION}:{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()[:12]
    cache = get_settings().cache_dir / f"street_lanes_v{CACHE_VERSION}_{key}.pkl"
    with _lock:
        data = pickle.loads(cache.read_bytes()) if cache.is_file() else None
        if data is None:
            data = _read(pbf)
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".tmp")
            tmp.write_bytes(pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL))
            tmp.replace(cache)
    return tuple(data), STRtree([w.geom for w in data])


def _enough(w: Way) -> bool | None:
    lanes = w.lanes
    if lanes is None and w.width is not None:
        lanes = int(w.width // LANE_WIDTH_M)
    if lanes is None:
        return None
    return lanes >= (2 if w.oneway else 3)


def judge_streets(closure: dict) -> list[StreetJudgement]:
    g = to_metric(from_geojson(closure["geometry"]))
    buf = g.buffer(float(closure.get("bufferMeters") or 30))
    all_ways, tree = ways()
    hits = []
    for i in tree.query(buf, predicate="intersects"):
        w = all_ways[int(i)]
        inside = w.geom.intersection(buf).length
        if inside > 0:
            hits.append((inside, w))
    if not hits:
        return []
    hits.sort(key=lambda h: -h[0])
    need = MIN_SHARE * max(g.length, 1.0)
    main = [w for inside, w in hits if inside >= need] or [hits[0][1]]
    return [StreetJudgement(w.osm_id, w.name, w.lanes, w.width, w.oneway, _enough(w)) for w in main]


def along_tram(closure: dict) -> bool:
    """The closure runs along a GTFS tram shape (within 10 m for at least half of its length)."""
    from app.city_reports.core import gtfs_shapes

    f = gtfs.feed()
    tram = set(f.routes.loc[f.routes.route_type == "0", "route_id"])
    ids = set(f.trips.loc[f.trips.route_id.isin(tram), "shape_id"])
    shapes = gtfs_shapes(f.sha256)
    g = to_metric(from_geojson(closure["geometry"]))
    if g.length <= 0:
        return False
    parts = [shapes[str(s)].buffer(TRAM_NEAR_M) for s in ids if str(s) in shapes and shapes[str(s)].distance(g) <= TRAM_NEAR_M]
    if not parts:
        return False
    from shapely.ops import unary_union

    return g.intersection(unary_union(parts)).length >= 0.5 * g.length


def verdict(closure: dict) -> tuple[bool, list[StreetJudgement], list[I18n]]:
    """(can judge and enough room, the streets, the reasons when not)."""
    streets = judge_streets(closure)
    reasons: list[I18n] = []
    if along_tram(closure):
        reasons.append(I18n(ro="lucrarea e pe o linie de tramvai: șinele sunt lucrarea",
                            en="the works are on a tram line: the tracks are the works"))
    if not streets:
        reasons.append(I18n(ro="nicio stradă OSM găsită în zona lucrării", en="no OSM street found in the works area"))
    for s in streets:
        label = s.name or s.osm_id
        if s.enough is None:
            reasons.append(I18n(ro=f"{label}: OSM nu are `lanes` și nici `width`", en=f"{label}: OSM has neither `lanes` nor `width`"))
        elif not s.enough:
            have = s.lanes if s.lanes is not None else f"lățime {s.width:g} m"
            have_en = s.lanes if s.lanes is not None else f"width {s.width:g} m"
            need_ro = "2 benzi pe sens unic" if s.oneway else "3 benzi pe stradă cu dublu sens"
            need_en = "2 lanes on a one-way street" if s.oneway else "3 lanes on a two-way street"
            reasons.append(I18n(ro=f"{label}: prea îngustă în OSM ({have}; ar trebui {need_ro})",
                                en=f"{label}: too narrow in OSM ({have_en}; would need {need_en})"))
    return (not reasons), streets, reasons
