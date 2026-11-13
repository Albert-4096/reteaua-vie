"""r5py (Conveyal R5) as the transit router for M4 access and M2 routing.

R5 runs in a JVM inside this process (JPype). The JVM starts on the first
call, not at import: importing this module is cheap and safe for the API.

- Heap: at most R5_MAX_MEMORY (default 8G; SPEC: the VM has 32 GB, R5 gets
  at most 8). r5py reads it from its command-line options, so the import sets
  `--max-memory` on a temporary argv.
- Networks: one TransportNetwork per (OSM pbf, GTFS zip). r5py caches the
  built network on disk (its cache dir, keyed by the input files' hash), so a
  network is built once (about 15 s) and later loads in a few seconds. Built
  networks stay in memory, LRU of NETWORKS_IN_MEMORY.

Public:
    available() -> bool                          Java + r5py importable
    network(gtfs_zip) -> r5py.TransportNetwork
    travel_times(gtfs_zip, origins, destinations, departure, max_minutes, ...) -> DataFrame
    itineraries(gtfs_zip, origin, destination, departure, ...) -> GeoDataFrame
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path

import geopandas as gpd
import pandas as pd

from app.config import TZ, get_settings

log = logging.getLogger("reteaua_vie.r5")

OSM_FILE = "osm/timisoara.osm.pbf"
NETWORKS_IN_MEMORY = 6
WALK_KMH = 4.8                  # SPEC §6.2 / §3.1
MAX_WALK_MIN_ACCESS = 15        # SPEC §6.4

_lock = threading.RLock()       # network building and the JVM start are not re-entrant
_networks: "OrderedDict[str, object]" = OrderedDict()
_r5py = None


def max_memory() -> str:
    return os.environ.get("R5_MAX_MEMORY", "8G")


def available() -> bool:
    """True if Java is installed and r5py can be imported."""
    if shutil.which("java") is None:
        return False
    try:
        _module()
    except Exception:  # noqa: BLE001 - any import failure means "no r5"
        log.exception("r5py import failed")
        return False
    return True


def _module():
    """Import r5py once, with the JVM heap limit set on its command-line options."""
    global _r5py
    if _r5py is not None:
        return _r5py
    with _lock:
        if _r5py is None:
            # The JVM is often started from a job thread. Destroying it at interpreter exit then
            # hangs or segfaults (R5's own thread pools); the OS frees it anyway.
            import jpype.config  # noqa: PLC0415

            jpype.config.destroy_jvm = False
            saved = sys.argv
            sys.argv = [saved[0] if saved else "reteaua-vie", "--max-memory", max_memory()]
            try:
                import r5py  # noqa: PLC0415 - slow import (JVM), only when routing is needed
            finally:
                sys.argv = saved
            _r5py = r5py
    return _r5py


def osm_pbf() -> Path:
    return get_settings().data_dir / OSM_FILE


def network(gtfs_zip: Path):
    """The R5 network for the city OSM extract + one GTFS zip (memory LRU, r5py disk cache)."""
    key = str(Path(gtfs_zip).resolve())
    with _lock:
        if key in _networks:
            _networks.move_to_end(key)
            return _networks[key]
        r5py = _module()
        net = r5py.TransportNetwork(str(osm_pbf()), [key])
        _networks[key] = net
        while len(_networks) > NETWORKS_IN_MEMORY:
            _networks.popitem(last=False)
        return net


def _naive_local(dt: datetime) -> datetime:
    """R5 takes local wall-clock time without an offset (the GTFS agency's zone)."""
    return dt.astimezone(TZ).replace(tzinfo=None) if dt.tzinfo else dt


def points_frame(ids: list, lons, lats) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"id": ids}, geometry=gpd.points_from_xy(lons, lats), crs="EPSG:4326")


def travel_times(gtfs_zip: Path, origins: gpd.GeoDataFrame, destinations: gpd.GeoDataFrame,
                 departure: datetime, max_minutes: int, max_walk_minutes: int = MAX_WALK_MIN_ACCESS,
                 time_window_minutes: int = 10) -> pd.DataFrame:
    """Walk + transit travel times (median over the departure window), columns from_id, to_id, travel_time.

    travel_time is NaN when the destination is not reached within max_minutes.
    """
    r5py = _module()
    net = network(gtfs_zip)
    ttm = r5py.TravelTimeMatrix(
        net, origins=origins, destinations=destinations,
        departure=_naive_local(departure),
        departure_time_window=timedelta(minutes=time_window_minutes),
        transport_modes=[r5py.TransportMode.TRANSIT, r5py.TransportMode.WALK],
        max_time=timedelta(minutes=max_minutes),
        max_time_walking=timedelta(minutes=max_walk_minutes),
        speed_walking=WALK_KMH,
    )
    return pd.DataFrame(ttm[["from_id", "to_id", "travel_time"]])


def itineraries(gtfs_zip: Path, origin: tuple[float, float], destination: tuple[float, float],
                departure: datetime, max_minutes: int = 120, max_walk_minutes: int = 13,
                max_rides: int = 3) -> gpd.GeoDataFrame:
    """Detailed walk + transit itineraries for one origin-destination pair (all options R5 finds)."""
    r5py = _module()
    net = network(gtfs_zip)
    o = points_frame([0], [origin[0]], [origin[1]])
    d = points_frame([1], [destination[0]], [destination[1]])
    return r5py.DetailedItineraries(
        net, origins=o, destinations=d,
        departure=_naive_local(departure),
        departure_time_window=timedelta(minutes=10),
        transport_modes=[r5py.TransportMode.TRANSIT, r5py.TransportMode.WALK],
        max_time=timedelta(minutes=max_minutes),
        max_time_walking=timedelta(minutes=max_walk_minutes),
        speed_walking=WALK_KMH,
        max_public_transport_rides=max_rides,
        snap_to_network=True,
    )
