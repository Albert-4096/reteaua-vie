"""`make precompute` hook: the OSM bike cache, the bike layer and the bike impact of the cases."""

from __future__ import annotations

import threading
import time

from app.m5_bike import bike
from app.m5_bike.layers import bike_layer
from app.m5_bike.osm_bike import bike_data


def warm_data() -> None:
    bike_data().seg_tree()
    bike_layer()


def warm(closure_ids: list[str]) -> None:
    t = time.perf_counter()
    warm_data()
    print(f"    bike OSM network and layer ({time.perf_counter() - t:.1f} s)", flush=True)
    for cid in closure_ids:
        t = time.perf_counter()
        r = bike.bike_impact(cid)
        print(f"    bike {cid}: {len(r.lanesAffected)} lanes, {len(r.parkingAffected)} parking, "
              f"{len(r.detourStress)} detour pieces ({time.perf_counter() - t:.1f} s)", flush=True)


def warm_in_background() -> threading.Thread:
    """Load the bike network in the API process, so the first request is fast."""
    th = threading.Thread(target=warm_data, name="warm-bike", daemon=True)
    th.start()
    return th
