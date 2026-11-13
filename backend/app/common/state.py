"""The JSON state store: $DATA_DIR/state/{closures,scenarios,published}/.

No database (SPEC §3.1). One JSON file per object:
    state/<kind>/<id>.json            the object itself (e.g. a Closure)
    state/<kind>/<id>.<part>.json     data attached to it (e.g. its last Analysis)

Conventions for closures (shared by the M1 agents):
    read("closures", cid)               -> Closure dict
    read("closures", cid, "analysis")   -> last Analysis with decisions applied
    read("closures", cid, "impact")     -> last Impact (used for list numbers)
    read("published", cid)              -> PublishResult dict (has publishedAt)

Writes are atomic (temp file + fsync + rename) and serialized with a file
lock, so the API and the worker process can share the directory.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from pydantic import BaseModel

from app.config import STATE_KINDS, TZ, get_settings

PART_ANALYSIS = "analysis"
PART_IMPACT = "impact"

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
_PART_RE = re.compile(r"^[a-z0-9_-]{1,40}$")
_thread_lock = threading.RLock()


def _check(kind: str, obj_id: str, part: str | None) -> None:
    if kind not in STATE_KINDS:
        raise ValueError(f"unknown state kind {kind!r}; use one of {STATE_KINDS}")
    if not _ID_RE.match(obj_id or ""):
        raise ValueError(f"invalid id {obj_id!r}")
    if part is not None and not _PART_RE.match(part):
        raise ValueError(f"invalid part {part!r}")


def kind_dir(kind: str) -> Path:
    d = get_settings().state_dir / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def path_for(kind: str, obj_id: str, part: str | None = None) -> Path:
    _check(kind, obj_id, part)
    name = f"{obj_id}.json" if part is None else f"{obj_id}.{part}.json"
    return kind_dir(kind) / name


@contextmanager
def locked() -> Iterator[None]:
    """Exclusive lock over the whole state dir (threads and processes)."""
    lock_path = get_settings().state_dir / ".lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _thread_lock:
        with open(lock_path, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)


def _to_jsonable(data: Any) -> Any:
    if isinstance(data, BaseModel):
        return data.model_dump(mode="json", by_alias=True)
    return data


def _atomic_write(path: Path, data: Any) -> None:
    payload = json.dumps(_to_jsonable(data), ensure_ascii=False, indent=1)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def read(kind: str, obj_id: str, part: str | None = None) -> dict | list | None:
    """The stored JSON, or None if it does not exist."""
    p = path_for(kind, obj_id, part)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def exists(kind: str, obj_id: str, part: str | None = None) -> bool:
    return path_for(kind, obj_id, part).is_file()


def write(kind: str, obj_id: str, data: Any, part: str | None = None) -> Path:
    """Store a dict or pydantic model atomically. Returns the file path."""
    p = path_for(kind, obj_id, part)
    with locked():
        _atomic_write(p, data)
    return p


def update(kind: str, obj_id: str, fn: Callable[[Any], Any], part: str | None = None) -> Any:
    """Read-modify-write under the lock. `fn(old_or_None)` returns the new value."""
    p = path_for(kind, obj_id, part)
    with locked():
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            old = None
        new = _to_jsonable(fn(old))
        _atomic_write(p, new)
    return new


def delete(kind: str, obj_id: str, part: str | None = None) -> bool:
    """Delete one object (part=None also deletes all its parts)."""
    with locked():
        removed = False
        targets = [path_for(kind, obj_id, part)]
        if part is None:
            targets += list(kind_dir(kind).glob(f"{obj_id}.*.json"))
        for t in targets:
            try:
                t.unlink()
                removed = True
            except FileNotFoundError:
                pass
    return removed


def list_ids(kind: str) -> list[str]:
    """Ids of the stored objects (parts are not listed), sorted."""
    out = []
    for p in kind_dir(kind).glob("*.json"):
        stem = p.name[:-5]
        if "." in stem or stem.startswith("."):
            continue
        out.append(stem)
    return sorted(out)


def list_all(kind: str) -> list[dict]:
    """All stored objects of a kind (skips ones deleted while listing)."""
    out = []
    for obj_id in list_ids(kind):
        obj = read(kind, obj_id)
        if obj is not None:
            out.append(obj)
    return out


def new_id(prefix: str) -> str:
    """A fresh id like 'cl_20261113_1830_a1b2c3' (Bucharest time + random)."""
    stamp = datetime.now(TZ).strftime("%Y%m%d_%H%M")
    return f"{prefix}_{stamp}_{secrets.token_hex(3)}"
