"""S1: GET /api/stops/{stopId}/status and GET /api/stops/search (CityApp and Timi read these)."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Query

from app.cityapp import status
from app.cityapp.models import StopHit, StopStatus
from app.common.city import load_network
from app.common.errors import invalid
from app.common.geo import project_lonlats
from app.common.timeutil import parse_iso
from app.config import TZ, now
from app.m1_disruption.matching import norm

router = APIRouter(tags=["S1 stop status"])

LIMIT = 20


@router.get("/stops/search", response_model=list[StopHit])
def search_stops(q: str | None = Query(None, description="name, ignoring case and diacritics"),
                 lat: float | None = None, lon: float | None = None,
                 radius: float = Query(400, gt=0, le=3000, description="metres, with lat and lon")) -> list[StopHit]:
    """Stops by name (`q`) and/or around a point (`lat`, `lon`, `radius`). At least one of the two."""
    if not q and (lat is None or lon is None):
        raise invalid("Give `q`, or `lat` and `lon`.")
    if (lat is None) != (lon is None):
        raise invalid("`lat` and `lon` go together.")
    net = load_network()
    dist = None
    if lat is not None:
        xy = project_lonlats([(lon, lat)])[0]
        dist = np.hypot(net.stop_xy[:, 0] - xy[0], net.stop_xy[:, 1] - xy[1])
    needle = norm(q) if q else ""
    hits = []
    for i, s in enumerate(net.stops):
        if needle and needle not in norm(s["name"]):
            continue
        if dist is not None and dist[i] > radius:
            continue
        hits.append((float(dist[i]) if dist is not None else 0.0, s["name"], s))
    hits.sort(key=lambda h: (h[0], h[1]))
    return [StopHit(stopId=s["id"], name=s["name"], location=s["location"], routeIds=sorted(s.get("routeIds") or []),
                    distanceMeters=int(round(d)) if dist is not None else None) for d, _, s in hits[:LIMIT]]


@router.get("/stops/{stop_id}/status", response_model=StopStatus)
def stop_status(stop_id: str, at: str | None = Query(None, description="ISO 8601 time; default: now (DEMO_NOW)")) -> StopStatus:
    try:
        when = parse_iso(at).astimezone(TZ) if at else now()
    except ValueError:
        raise invalid("`at` must be an ISO 8601 time") from None
    return status.stop_status(stop_id, when)
