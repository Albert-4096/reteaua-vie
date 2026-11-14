"""R7-B: poster scan counter (public QR page -> POST, back office -> GET).

Privacy: a scan stores only (closure, stop, hour bucket) as a counter. No IP, no
user agent, no cookie, no id. Stored in $DATA_DIR/state/scans/<closureId>.json:
    {"closureId": ..., "stops": {"<stopId>": {"<hour bucket>": n}}}

Abuse limit, per process and anonymous (in-memory timestamps of recent accepted
scans, never tied to a visitor): at most MAX_PER_STOP_PER_MIN per closure+stop and
MAX_PER_MIN overall in any 60 s; beyond that the answer is 429 RATE_LIMITED. A
closure holds at most MAX_STOPS distinct stop ids.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from datetime import datetime

from fastapi import APIRouter, Query

from app.common import state
from app.common.errors import ApiError, invalid, not_found
from app.common.timeutil import iso
from app.config import TZ, get_settings
from app.models.base import Provenance
from app.models.v2 import ScanAck, ScanCounts, ScanStop

router = APIRouter(tags=["R7 scans"])

MAX_PER_STOP_PER_MIN = 20
MAX_PER_MIN = 120
MAX_STOPS = 300
WINDOW_SEC = 60.0

_STOP_RE = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
_lock = threading.Lock()
_recent_all: deque[float] = deque()
_recent_stop: dict[tuple[str, str], deque[float]] = {}


def _allow(closure_id: str, stop: str, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    with _lock:
        cutoff = now - WINDOW_SEC
        while _recent_all and _recent_all[0] < cutoff:
            _recent_all.popleft()
        for k in [k for k, q in _recent_stop.items() if not q or q[-1] < cutoff]:
            del _recent_stop[k]
        q = _recent_stop.setdefault((closure_id, stop), deque())
        while q and q[0] < cutoff:
            q.popleft()
        if len(_recent_all) >= MAX_PER_MIN or len(q) >= MAX_PER_STOP_PER_MIN:
            return False
        _recent_all.append(now)
        q.append(now)
        return True


def _bucket(dt: datetime | None = None) -> str:
    dt = (dt or datetime.now(TZ)).astimezone(TZ).replace(minute=0, second=0, microsecond=0)
    return iso(dt)


def _closure_exists(closure_id: str) -> None:
    try:
        ok = state.exists("closures", closure_id)
    except ValueError:
        ok = False
    if not ok:
        raise not_found(f"No closure {closure_id}.")


@router.post("/closures/{closure_id}/scans", response_model=ScanAck)
def post_scan(closure_id: str, stop: str = Query(..., description="stopId on the poster QR code")) -> ScanAck:
    _closure_exists(closure_id)
    if not _STOP_RE.match(stop):
        raise invalid("stop must be 1-40 characters of letters, digits, '_', '.', '-'.")
    if not _allow(closure_id, stop):
        raise ApiError(429, "RATE_LIMITED", "Too many scans, try again in a minute.")
    bucket = _bucket()

    def add(old: dict | None) -> dict:
        data = old or {"closureId": closure_id, "stops": {}}
        stops = data.setdefault("stops", {})
        if stop not in stops and len(stops) >= MAX_STOPS:
            raise invalid("Too many distinct stops for this closure.")
        b = stops.setdefault(stop, {})
        b[bucket] = int(b.get(bucket, 0)) + 1
        return data

    state.update("scans", closure_id, add)
    return ScanAck(closureId=closure_id, stopId=stop)


@router.get("/closures/{closure_id}/scans", response_model=ScanCounts)
def get_scans(closure_id: str) -> ScanCounts:
    _closure_exists(closure_id)
    data = state.read("scans", closure_id) or {"stops": {}}
    rows: list[ScanStop] = []
    for stop_id, buckets in data.get("stops", {}).items():
        keys = sorted(buckets)
        rows.append(ScanStop(stopId=stop_id, count=sum(buckets.values()), firstBucket=keys[0], lastBucket=keys[-1]))
    rows.sort(key=lambda r: (-r.count, r.stopId))
    p = state.path_for("scans", closure_id)
    from app.common.timeutil import file_mtime

    fetched = file_mtime(p) if p.is_file() else datetime.now(TZ)
    return ScanCounts(
        closureId=closure_id,
        total=sum(r.count for r in rows),
        stops=rows,
        provenance=[
            Provenance(
                source="Rețeaua Vie, scanări afișe (QR)",
                url=None,
                version=None,
                fetchedAt=iso(fetched),
                note="Doar contor pe stație și oră; fără IP, agent sau cookie. Fiecare deschidere a paginii QR, nu persoane unice.",
            )
        ],
    )
