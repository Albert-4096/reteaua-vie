"""Slow work as jobs (CONTRACT "Events and jobs").

    from app.common.jobs import respond

    @router.get("/closures/{cid}/access")
    def access(cid: str, dest: str = "hospital", minutes: int = 30):
        key = f"access:{cid}:{dest}:{minutes}:{closure_fingerprint(cid)}"
        return respond(key, lambda: compute_access(cid, dest, minutes))

`respond(key, compute)` returns the model (HTTP 200) when its result is cached or the
computation finishes inside `sync_budget_s`; otherwise it answers `202 {"jobId"}` and the
computation goes on in a small thread pool. `GET /api/jobs/{jobId}` (app.common.api_jobs)
then returns the CONTRACT `Job`. A finished result is cached under
$DATA_DIR/cache/jobs/<sha256 of key>.json, so the next call (and the next process: API or
worker) answers 200 at once. The key must therefore name everything the result depends on;
`closure_fingerprint(cid)` covers a stored closure and its decisions.

An ApiError raised inside the budget propagates as the normal error response; any error
after the budget becomes `Job.state = "error"` with its code and message.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import tempfile
import threading
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.common.errors import ApiError
from app.common.timeutil import iso
from app.config import get_settings, real_now
from app.models.v2 import Job, JobError

log = logging.getLogger("reteaua_vie.jobs")

MAX_WORKERS = 4
FILE_MODE = 0o664

_pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="job")
_lock = threading.Lock()


@dataclass
class _JobState:
    job_id: str
    key: str
    state: str = "queued"  # queued | running | done | error
    result: BaseModel | None = None
    error: JobError | None = None
    future: Future | None = field(default=None, repr=False)


_jobs: dict[str, _JobState] = {}  # job id -> state, this process only


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def job_id_for(key: str) -> str:
    """Deterministic: the same key always gets the same job id (also across restarts)."""
    return f"job_{key_hash(key)[:32]}"


def cache_dir() -> Path:
    d = get_settings().cache_dir / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path(key: str) -> Path:
    return cache_dir() / f"{key_hash(key)}.json"


def _model_path(model: BaseModel) -> str:
    cls = type(model)
    return f"{cls.__module__}:{cls.__qualname__}"


def _load_model(path: str, data: Any) -> BaseModel:
    module, _, qualname = path.partition(":")
    obj: Any = importlib.import_module(module)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj.model_validate(data)


def _write_cache(key: str, model: BaseModel) -> None:
    payload = {
        "key": key,
        "model": _model_path(model),
        "computedAt": iso(real_now()),
        "result": model.model_dump(mode="json", by_alias=True),
    }
    path = _cache_path(key)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.chmod(tmp, FILE_MODE)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _read_cache_file(path: Path) -> BaseModel | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _load_model(payload["model"], payload["result"])
    except FileNotFoundError:
        return None
    except Exception:  # a stale cache (model changed): recompute instead of failing
        log.warning("job cache %s unreadable; ignored", path.name, exc_info=True)
        return None


def cached(key: str) -> BaseModel | None:
    """The cached result for `key`, or None."""
    return _read_cache_file(_cache_path(key))


def invalidate(key: str) -> bool:
    """Drop the cached result of `key` (e.g. after the inputs changed)."""
    with _lock:
        _jobs.pop(job_id_for(key), None)
    try:
        _cache_path(key).unlink()
        return True
    except FileNotFoundError:
        return False


def compute_and_cache(key: str, compute: Callable[[], BaseModel]) -> BaseModel:
    """Synchronous: the cached result, or compute and cache it now (for warm.py)."""
    hit = cached(key)
    if hit is not None:
        return hit
    result = compute()
    _write_cache(key, result)
    return result


def _run(job: _JobState, compute: Callable[[], BaseModel]) -> BaseModel:
    job.state = "running"
    try:
        result = compute()
        if not isinstance(result, BaseModel):
            raise TypeError(f"job {job.key!r} returned {type(result).__name__}, not a pydantic model")
        _write_cache(job.key, result)
    except ApiError as e:
        job.error = JobError(code=e.code, message=e.message)
        job.state = "error"
        raise
    except Exception as e:
        log.exception("job %s failed", job.key)
        job.error = JobError(code="INTERNAL", message=f"{type(e).__name__}: {e}")
        job.state = "error"
        raise
    job.result = result
    job.state = "done"
    return result


def submit(key: str, compute: Callable[[], BaseModel]) -> _JobState:
    """Start (or join) the job for `key` in the pool."""
    jid = job_id_for(key)
    with _lock:
        job = _jobs.get(jid)
        if job is not None and job.state in ("queued", "running", "done"):
            return job
        job = _JobState(job_id=jid, key=key)
        _jobs[jid] = job
        job.future = _pool.submit(_run, job, compute)
    return job


def respond(key: str, compute: Callable[[], BaseModel], sync_budget_s: float = 3.0):
    """The model (200) if cached or done within the budget, else `202 {"jobId"}`."""
    hit = cached(key)
    if hit is not None:
        return hit
    job = submit(key, compute)
    if job.state == "done" and job.result is not None:
        return job.result
    try:
        return job.future.result(timeout=max(sync_budget_s, 0.0))  # type: ignore[union-attr]
    except FutureTimeout:
        return JSONResponse(status_code=202, content={"jobId": job.job_id})
    # an ApiError (or any error) inside the budget propagates as the normal error response


def get_job(job_id: str) -> Job | None:
    """The CONTRACT Job, from this process's memory or else from the result cache."""
    with _lock:
        job = _jobs.get(job_id)
    if job is not None:
        result = job.result.model_dump(mode="json", by_alias=True) if job.result is not None else None
        return Job(jobId=job.job_id, state=job.state, progress=None,  # type: ignore[arg-type]
                   result=result, error=job.error)
    if not job_id.startswith("job_") or len(job_id) != 36:
        return None
    prefix = job_id[4:]
    for path in cache_dir().glob(f"{prefix}*.json"):
        model = _read_cache_file(path)
        if model is not None:
            return Job(jobId=job_id, state="done", progress=None,
                       result=model.model_dump(mode="json", by_alias=True), error=None)
    return None


def closure_fingerprint(closure_id: str) -> str:
    """A short hash of what a stored closure's results depend on, for job keys.

    Covers the closure input and the person's stop decisions; not its status, so
    publishing a prepared case does not throw its cached results away.
    """
    from app.common import state

    closure = state.read("closures", closure_id) or {}
    inputs = {k: v for k, v in closure.items() if k not in ("status", "createdAt")}
    analysis = state.read("closures", closure_id, state.PART_ANALYSIS) or {}
    rows = sorted(
        (str(r.get("stopId")), str(r.get("routeId")), str(r.get("directionId")), str(r.get("confirmed")))
        for r in analysis.get("stops") or []
    )
    blob = json.dumps([inputs, analysis.get("feedVersion"), rows], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
