"""GET /api/live/replay?from=&to=&stepSec=60: our recording as frames, for the map's time slider (L5).

Reads only our recording; never a call to the city. Window at most 6 h, step at least 15 s.
Columnar rows: [vehicleId, routeId, lat, lon, bearing, delaySec|null] (see `columns`).
"""

from __future__ import annotations

import gzip

from fastapi import APIRouter, Query, Request, Response

from app.common.errors import invalid
from app.common.timeutil import parse_iso
from app.live import replay

router = APIRouter(tags=["live"])
DEFAULT_FROM = "2026-11-14T06:00:00+02:00"
DEFAULT_TO = "2026-11-14T10:41:00+02:00"


def _time(value: str, name: str):
    try:
        return parse_iso(value.strip().replace(" ", "+"))  # an unencoded '+' arrives as a space
    except ValueError:
        raise invalid(f"`{name}` must be an ISO 8601 time, e.g. 2026-11-14T06:00:00+02:00")


@router.get("/live/replay")
def live_replay(request: Request,
                from_: str = Query(DEFAULT_FROM, alias="from", description="ISO time; default Sat 14 Nov 06:00 Bucharest"),
                to: str = Query(DEFAULT_TO, description="ISO time; default Sat 14 Nov 10:41 Bucharest"),
                stepSec: int = Query(replay.DEFAULT_STEP_SEC, description="seconds between frames, at least 15")) -> Response:
    start, end = _time(from_, "from"), _time(to, "to")
    if start >= end:
        raise invalid("`from` must be before `to`")
    if end - start > replay.MAX_WINDOW:
        raise invalid("the window may be at most 6 h")
    if stepSec < replay.MIN_STEP_SEC:
        raise invalid(f"`stepSec` must be at least {replay.MIN_STEP_SEC}")
    body = replay.replay_gz(start, end, stepSec)
    headers = {"Cache-Control": "public, max-age=300", "Vary": "Accept-Encoding"}
    if "gzip" in request.headers.get("accept-encoding", ""):
        return Response(body, media_type="application/json", headers={**headers, "Content-Encoding": "gzip"})
    return Response(gzip.decompress(body), media_type="application/json", headers=headers)
