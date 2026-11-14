"""Signalised pedestrian crossings from our OSM extract, with their `traffic_signals:sound` tag."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.common import provenance as prov
from app.common.geo import project_lonlats
from app.config import get_settings
from app.models.base import Provenance

OSM_FILE = "osm/timisoara.osm.pbf"
CACHE_VERSION = 1
RADIUS_M = 100.0


def _pbf() -> Path:
    return get_settings().data_dir / OSM_FILE


def _cache(pbf: Path) -> Path:
    st = pbf.stat()
    key = hashlib.sha1(f"{CACHE_VERSION}:{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()[:12]
    return get_settings().cache_dir / f"osm_signal_crossings_v{CACHE_VERSION}_{key}.json"


def _norm(v) -> str | None:
    return v if v in ("yes", "no") else None


def _read(pbf: Path) -> list[dict]:
    import pyrosm  # slow import, only when building the cache

    osm = pyrosm.OSM(str(pbf))
    g = osm.get_data_by_custom_criteria(
        custom_filter={"crossing": ["traffic_signals"]}, filter_type="keep",
        keep_nodes=True, keep_ways=False, keep_relations=False, extra_attributes=["traffic_signals:sound"])
    out = []
    if g is not None:
        for row in g.to_dict("records"):
            out.append({"osmId": f"node/{int(row['id'])}", "lon": float(row["lon"]), "lat": float(row["lat"]),
                        "sound": _norm(row.get("traffic_signals:sound"))})
    return sorted(out, key=lambda c: c["osmId"])


@lru_cache(maxsize=1)
def load() -> tuple[list[dict], np.ndarray] | None:
    pbf = _pbf()
    if not pbf.is_file():
        return None
    cache = _cache(pbf)
    if cache.is_file():
        rows = json.loads(cache.read_text(encoding="utf-8"))
    else:
        rows = _read(pbf)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rows), encoding="utf-8")
    xy = project_lonlats((r["lon"], r["lat"]) for r in rows) if rows else np.zeros((0, 2))
    return rows, xy


def nearest(stop_xy: np.ndarray) -> list[dict | None]:
    """For each stop (metric xy): the nearest signalised crossing within RADIUS_M, else None."""
    data = load()
    if data is None or not len(data[0]):
        return [None] * len(stop_xy)
    rows, xy = data
    out: list[dict | None] = []
    for p in stop_xy:
        d = np.hypot(xy[:, 0] - p[0], xy[:, 1] - p[1])
        i = int(np.argmin(d))
        out.append({"osmId": rows[i]["osmId"], "distanceMeters": round(float(d[i])),
                    "sound": rows[i]["sound"]} if d[i] <= RADIUS_M else None)
    return out


def provenance() -> Provenance:
    return prov.for_file("OpenStreetMap", _pbf(), "https://www.openstreetmap.org", None,
                         "crossing=traffic_signals; etichetă traffic_signals:sound")
