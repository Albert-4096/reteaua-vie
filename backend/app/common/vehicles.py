"""Reader for our live-vehicle recording ($LIVE_DIR/vehicles/YYYYMMDD-HH.jsonl.gz).

One file per UTC hour, one JSON line per 15 s poll:
{fetchedAt, realtimeAgeSec, refreshInSec, vehicles: [{id, routeId, tripId,
directionId, headsign, lat, lon, bearing, speed, stopId, stopSequence, status,
delaySec, updatedAt, wheelchair}]}.
The newest file may be open for writing; a cut last line is skipped.
Requests never call the city endpoint: they read this recording only.
"""

from __future__ import annotations

import gzip
import json
import zlib
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from app.common import provenance as prov
from app.common.timeutil import from_unix, iso, parse_iso
from app.config import get_settings


def vehicles_dir() -> Path:
    return get_settings().live_dir / "vehicles"


def recording_files() -> list[tuple[Path, datetime]]:
    """[(path, start of its UTC hour)] sorted by time."""
    d = vehicles_dir()
    if not d.is_dir():
        return []
    out = []
    for p in d.glob("*.jsonl.gz"):
        stem = p.name[: -len(".jsonl.gz")]
        try:
            hour = datetime.strptime(stem, "%Y%m%d-%H").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        out.append((p, hour))
    out.sort(key=lambda x: x[1])
    return out


def _read_lines(path: Path) -> list[dict]:
    """All complete snapshots of one file (tolerates a file still being written)."""
    snaps: list[dict] = []
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    snaps.append(json.loads(line))
                except json.JSONDecodeError:
                    break
    except (EOFError, OSError, zlib.error):
        pass  # truncated tail of the file being written
    return snaps


@lru_cache(maxsize=8)
def _read_cached(path: str, size: int, mtime: float) -> tuple[dict, ...]:
    return tuple(_read_lines(Path(path)))


def read_file(path: Path) -> tuple[dict, ...]:
    st = path.stat()
    return _read_cached(str(path), st.st_size, st.st_mtime)


def snapshot_time(snap: dict) -> datetime:
    return parse_iso(snap["fetchedAt"])


def newest_snapshot() -> dict | None:
    """The newest complete snapshot in the recording, or None if there is none."""
    for path, _hour in reversed(recording_files()):
        snaps = read_file(path)
        if snaps:
            return snaps[-1]
    return None


def iter_snapshots(start: datetime, end: datetime) -> Iterator[dict]:
    """Snapshots with fetchedAt in [start, end), oldest first."""
    s_utc = start.astimezone(timezone.utc)
    e_utc = end.astimezone(timezone.utc)
    for path, hour in recording_files():
        if hour + timedelta(hours=1) <= s_utc or hour >= e_utc:
            continue
        for snap in read_file(path):
            t = snapshot_time(snap)
            if start <= t < end:
                yield snap


def recording_span() -> tuple[datetime, datetime] | None:
    """(first, last) snapshot time of the whole recording."""
    files = recording_files()
    if not files:
        return None
    first = next((s for p, _ in files for s in read_file(p)[:1]), None)
    last = newest_snapshot()
    if first is None or last is None:
        return None
    return snapshot_time(first), snapshot_time(last)


def vehicle_feature(v: dict) -> dict:
    """One recorded vehicle -> GeoJSON point Feature (CONTRACT LayerCollection 'vehicles')."""
    upd = v.get("updatedAt")
    direction = v.get("directionId")
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [float(v["lon"]), float(v["lat"])]},
        "properties": {
            "vehicleId": str(v.get("id")),
            "routeId": v.get("routeId"),
            "tripId": v.get("tripId"),
            "directionId": direction if direction in (0, 1) else None,
            "stopId": str(v["stopId"]) if v.get("stopId") is not None else None,
            "status": v.get("status"),
            "delaySec": int(v["delaySec"]) if v.get("delaySec") is not None else None,
            "wheelchair": v.get("wheelchair"),
            "updatedAt": iso(from_unix(upd)) if isinstance(upd, (int, float)) else None,
            # additive, optional: for the map arrow and label
            "headsign": v.get("headsign"),
            "bearing": v.get("bearing"),
        },
    }


def vehicles_layer(route_id: str | None = None) -> dict:
    """LayerCollection of the newest recorded snapshot (optionally one route)."""
    snap = newest_snapshot()
    if snap is None:
        return {"type": "FeatureCollection", "layer": "vehicles", "features": [], "provenance": [
            prov.provenance("CityApp vehicule live, înregistrarea noastră / our recording",
                            datetime.now(timezone.utc), prov.CITY_VEHICLES_URL, None,
                            "Nu există înregistrare / no recording yet").model_dump()]}
    t = snapshot_time(snap)
    vehicles = [v for v in snap.get("vehicles", [])
                if v.get("lat") is not None and v.get("lon") is not None
                and (route_id is None or v.get("routeId") == route_id)]
    age = (datetime.now(timezone.utc) - t).total_seconds()
    note = (f"Înregistrare reală, {iso(t)} (acum {int(age)} s) / real recording; "
            f"{len(vehicles)} vehicule în instantaneu / vehicles in snapshot")
    return {
        "type": "FeatureCollection",
        "layer": "vehicles",
        "features": [vehicle_feature(v) for v in vehicles],
        "provenance": [prov.vehicles_provenance(t, note).model_dump()],
    }
