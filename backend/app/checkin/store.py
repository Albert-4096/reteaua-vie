"""Check-in storage: $DATA_DIR/state/checkin/. No IP, no user agent, no account, no name, no position.

- stickers.json   the sticker registry (sticker -> route + direction, `simulated`)
- salt-YYYYMMDD   a random salt per receipt day; deleted with the day's rows
- rows-YYYYMMDD   raw rows of that receipt day: {id, at, receivedAt, stickerId, routeId, directionId, tripId,
                  stopId, device (salted hash, 16 hex), simulated}; kept RETENTION, then folded into counts
- counts.json     counts only, per day and route and trip (no device, no time of day finer than first/last)
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import tempfile
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from app.config import TZ, get_settings

RETENTION = timedelta(hours=48)
_lock = threading.RLock()

# The demo registry: one test sticker stands in for a vehicle of line 23 (the line with no vehicle on 14 Nov).
DEFAULT_STICKERS = {
    "test-l23": {"routeId": "R_AB_23", "directionId": 0, "simulated": True,
                 "note": "autocolant de test pentru linia 23, sens 0 / test sticker for line 23, direction 0"},
}


def _dir() -> Path:
    d = get_settings().state_dir / "checkin"
    d.mkdir(parents=True, exist_ok=True)
    return d


@contextmanager
def locked() -> Iterator[None]:
    with _lock:
        with open(_dir() / ".lock", "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)


def _read(name: str, default: Any) -> Any:
    p = _dir() / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def _write(name: str, data: Any) -> None:
    p = _dir() / name
    fd, tmp = tempfile.mkstemp(dir=_dir(), prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, 0o664)
    os.replace(tmp, p)


def stickers() -> dict[str, dict]:
    with locked():
        reg = _read("stickers.json", None)
        if reg is None:
            reg = DEFAULT_STICKERS
            _write("stickers.json", reg)
        return reg


def _day(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%Y%m%d")


def device_hash(deviceKey: str, received: datetime) -> str:
    """Salted hash of the browser's random id; the salt is per receipt day, so it rotates daily."""
    name = f"salt-{_day(received)}.json"
    with locked():
        salt = _read(name, None)
        if salt is None:
            salt = secrets.token_hex(16)
            _write(name, salt)
    return hashlib.sha256(f"{salt}:{deviceKey}".encode()).hexdigest()[:16]


def add_row(row: dict, received: datetime) -> None:
    name = f"rows-{_day(received)}.json"
    with locked():
        rows = _read(name, [])
        rows.append(row)
        _write(name, rows)
    purge(received)


def _rows_files() -> list[tuple[str, date]]:
    out = []
    for p in _dir().glob("rows-*.json"):
        try:
            out.append((p.name, datetime.strptime(p.stem[5:], "%Y%m%d").date()))
        except ValueError:
            pass
    return sorted(out, key=lambda x: x[1])


def purge(now: datetime) -> int:
    """Rows received more than RETENTION ago are folded into counts.json (no device, no time of day) and deleted;
    a day's salt goes with its last row."""
    cutoff = now.astimezone(TZ) - RETENTION
    n = 0
    with locked():
        for name, day in _rows_files():
            rows = _read(name, [])
            old = [r for r in rows if datetime.fromisoformat(r["receivedAt"]) < cutoff]
            if not old:
                continue
            counts = _read("counts.json", {})
            for r in old:
                d = counts.setdefault(r["at"][:10], {}).setdefault(r["routeId"], {}).setdefault(
                    r["tripId"], {"count": 0, "simulated": 0, "stops": {}})
                d["count"] += 1
                d["simulated"] += 1 if r.get("simulated") else 0
                if r.get("stopId"):
                    d["stops"][r["stopId"]] = d["stops"].get(r["stopId"], 0) + 1
                n += 1
            _write("counts.json", counts)
            keep = [r for r in rows if r not in old]
            if keep:
                _write(name, keep)
            else:
                (_dir() / name).unlink(missing_ok=True)
                (_dir() / f"salt-{name[5:]}").unlink(missing_ok=True)
    return n


def raw_rows() -> list[dict]:
    with locked():
        out: list[dict] = []
        for name, _ in _rows_files():
            out.extend(_read(name, []))
        return out


def archived_counts() -> dict:
    with locked():
        return _read("counts.json", {})
