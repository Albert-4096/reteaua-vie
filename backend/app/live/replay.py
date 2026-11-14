"""L5: replay of our own recording, one frame per step (GET /api/live/replay).

A frame at time t is the last recorded snapshot at or before t, kept only when it is at most MAX_AGE_SEC old.
Nothing is interpolated and no vehicle is invented: a frame lists exactly the vehicles of that snapshot. A
step with no snapshot that fresh (a hole in the recording) is a gap frame `{t, gap: true}`.
"""

from __future__ import annotations

import bisect
import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone

from app.common import gtfs, vehicles
from app.common import provenance as prov
from app.common.timeutil import iso
from app.config import TZ, get_settings, real_now
from app.observed import store

MAX_AGE_SEC = 30
MIN_STEP_SEC = 15
MAX_WINDOW = timedelta(hours=6)
DEFAULT_STEP_SEC = 60
CACHE_VERSION = 1
LABEL = {"ro": "Din datele live ale Primăriei, înregistrate de noi la 15 s",
         "en": "From the City Hall's live data, recorded by us every 15 s"}
GAP_NOTE = {"ro": "gol în înregistrare: fără vehicul în datele live pentru acest moment (nu înseamnă că nu a circulat nimic)",
            "en": "gap in our recording: no vehicle in the live data for this moment (not proof that nothing ran)"}


def _snapshots(start: datetime, end: datetime) -> tuple[list[float], list[dict]]:
    """Timestamps and snapshots of [start - MAX_AGE, end], oldest first."""
    lo = start - timedelta(seconds=MAX_AGE_SEC)
    ts, snaps = [], []
    for s in vehicles.iter_snapshots(lo, end + timedelta(seconds=1)):
        ts.append(vehicles.snapshot_time(s).timestamp())
        snaps.append(s)
    return ts, snaps


def _row(v: dict) -> list:
    d = v.get("delaySec")
    b = v.get("bearing")
    return [str(v.get("id")), v.get("routeId"), round(float(v["lat"]), 5), round(float(v["lon"]), 5),
            int(round(b)) if isinstance(b, (int, float)) else None,
            int(d) if isinstance(d, (int, float)) else None]


def build(start: datetime, end: datetime, step: int) -> dict:
    ts, snaps = _snapshots(start, end)
    frames, used = [], set()
    t = start.timestamp()
    e = end.timestamp()
    while t <= e:
        i = bisect.bisect_right(ts, t) - 1
        label = iso(datetime.fromtimestamp(t, tz=TZ))
        if i < 0 or t - ts[i] > MAX_AGE_SEC:
            frames.append({"t": label, "gap": True})
        else:
            rows = [_row(v) for v in snaps[i].get("vehicles") or [] if v.get("lat") is not None and v.get("lon") is not None]
            used.update(r[1] for r in rows)
            frames.append({"t": label, "vehicles": rows})
        t += step
    f = gtfs.feed(start)
    meta = f.routes.set_index("route_id")
    routes = {}
    for rid in sorted(x for x in used if x):
        if rid in meta.index:
            r = meta.loc[rid]
            color = str(r.route_color or "").strip().lstrip("#")
            routes[rid] = {"shortName": str(r.route_short_name), "color": color.lower() or None}
        else:
            routes[rid] = {"shortName": rid, "color": None}
    span = vehicles.recording_span()
    rec = None
    if span:
        ro, en = store.label(*span)
        rec = {"from": iso(span[0]), "to": iso(span[1]), "label": {"ro": ro, "en": en}}
    got = [fr for fr in frames if not fr.get("gap")]
    return {
        "window": {"start": iso(start), "end": iso(end)}, "stepSec": step, "maxAgeSec": MAX_AGE_SEC,
        "columns": ["vehicleId", "routeId", "lat", "lon", "bearing", "delaySec"],
        "frameCount": len(frames), "gapCount": len(frames) - len(got),
        "recording": rec, "label": LABEL, "gapNote": GAP_NOTE, "routes": routes, "frames": frames,
        "provenance": [f.provenance.model_dump(),
                       prov.vehicles_provenance(
                           datetime.fromtimestamp(ts[-1], tz=timezone.utc) if ts else real_now(),
                           f"{LABEL['ro']}; fără interpolare, un cadru = ultimul instantaneu cel mult {MAX_AGE_SEC} s vechi; "
                           f"fereastra {iso(start)} – {iso(end)}").model_dump()],
    }


def replay_gz(start: datetime, end: datetime, step: int) -> bytes:
    """The response as gzip bytes, cached on disk when every snapshot of the window is final."""
    last = vehicles.newest_snapshot()
    final = last is not None and vehicles.snapshot_time(last) > end + timedelta(minutes=2)
    key = hashlib.sha1(f"{CACHE_VERSION}|{start.timestamp()}|{end.timestamp()}|{step}|{store._stamp()}".encode()).hexdigest()[:20]
    path = get_settings().cache_dir / "replay" / f"{key}.json.gz"
    if final and path.is_file():
        return path.read_bytes()
    out = gzip.compress(json.dumps(build(start, end, step), ensure_ascii=False, separators=(",", ":")).encode(), 6)
    if final:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(out)
        except OSError:
            pass
    return out
