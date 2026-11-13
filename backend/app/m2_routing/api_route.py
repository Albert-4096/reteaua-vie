"""GET /api/route: a walk + transit trip that avoids the suspended stops (M2, a service for CityApp; job)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.common.errors import invalid
from app.common.jobs import respond
from app.common.timeutil import parse_iso
from app.config import TZ, now
from app.m2_routing import plan
from app.models.v2 import JobAccepted, RoutePlan

router = APIRouter(tags=["m2-routing"])

AREA = (21.10, 45.68, 21.35, 45.83)   # the OSM extract (SPEC §4)


def parse_lonlat(value: str, name: str) -> tuple[float, float]:
    try:
        lon, lat = (float(x) for x in value.split(","))
    except ValueError:
        raise invalid(f"`{name}` must be lon,lat") from None
    if not (AREA[0] <= lon <= AREA[2] and AREA[1] <= lat <= AREA[3]):
        raise invalid(f"`{name}` is outside Timișoara ({AREA[0]}..{AREA[2]} E, {AREA[1]}..{AREA[3]} N); "
                      f"give lon,lat", code="OUT_OF_AREA")
    return lon, lat


@router.get("/route", response_model=RoutePlan,
            responses={202: {"model": JobAccepted, "description": "Still computing: poll GET /api/jobs/{jobId}"}})
def route(from_: str = Query(..., alias="from", description="lon,lat"),
          to: str = Query(..., description="lon,lat"),
          at: str | None = Query(None, description="departure time, ISO 8601 with offset; default: now (DEMO_NOW)")):
    frm, dst = parse_lonlat(from_, "from"), parse_lonlat(to, "to")
    try:
        when = parse_iso(at).astimezone(TZ) if at else now()
    except ValueError:
        raise invalid("`at` must be an ISO 8601 time") from None
    return respond(plan.route_key(frm, dst, when), lambda: plan.plan_route(frm, dst, when))
