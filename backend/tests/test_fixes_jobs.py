"""app.common.jobs: fast path 200, slow path 202 then done, cached second call 200, errors."""

from __future__ import annotations

import time

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app import config
from app.common import jobs
from app.common.api_jobs import router as jobs_router
from app.common.errors import ApiError
from app.models.base import Provenance


@pytest.fixture
def client(tmp_path, monkeypatch):
    real = config.get_settings()
    fake = config.Settings(env_file=None, data_dir=tmp_path, live_dir=real.live_dir,
                           demo_now=real.demo_now, data_freeze=False, public_base_url=real.public_base_url)
    monkeypatch.setattr(config, "get_settings", lambda: fake)
    monkeypatch.setattr(jobs, "get_settings", lambda: fake)
    monkeypatch.setattr(jobs, "_jobs", {})
    calls = {"n": 0}

    def model(note: str) -> Provenance:
        calls["n"] += 1
        return Provenance(source="test", url=None, version=None, fetchedAt="2026-11-08T12:00:00+02:00", note=note)

    def slow(note: str) -> Provenance:
        time.sleep(0.5)
        return model(note)

    def fail(code: str):
        def run():
            time.sleep(0.3)
            if code == "API":
                raise ApiError(422, "OUTSIDE_FEED", "window outside every timetable")
            raise RuntimeError("boom")
        return run

    r = APIRouter()

    @r.get("/fast")
    def fast():
        return jobs.respond("fast", lambda: model("fast"))

    @r.get("/slow")
    def slow_ep():
        return jobs.respond("slow", lambda: slow("slow"), sync_budget_s=0.05)

    @r.get("/fail/{code}")
    def fail_ep(code: str, budget: float = 0.05):
        return jobs.respond(f"fail:{code}", fail(code), sync_budget_s=budget)

    from app.main import _api_error

    app = FastAPI()
    app.add_exception_handler(ApiError, _api_error)
    app.include_router(r, prefix="/api")
    app.include_router(jobs_router, prefix="/api")
    c = TestClient(app)
    c.calls = calls  # type: ignore[attr-defined]
    return c


def _poll(client, job_id: str, timeout: float = 5.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["state"] in ("done", "error"):
            return body
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_fast_path_200(client):
    r = client.get("/api/fast")
    assert r.status_code == 200 and r.json()["note"] == "fast"


def test_slow_path_202_then_done_then_cached(client):
    r = client.get("/api/slow")
    assert r.status_code == 202
    job_id = r.json()["jobId"]
    assert job_id == jobs.job_id_for("slow")
    body = _poll(client, job_id)
    assert body["state"] == "done" and body["result"]["note"] == "slow" and body["error"] is None
    assert client.calls["n"] == 1
    r2 = client.get("/api/slow")
    assert r2.status_code == 200 and r2.json()["note"] == "slow"
    assert client.calls["n"] == 1  # served from the cache, not recomputed
    jobs._jobs.clear()  # a new process: the job is still found through the result cache
    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "done"
    assert (jobs.cache_dir() / f"{jobs.key_hash('slow')}.json").stat().st_mode & 0o777 == 0o664


def test_error_after_budget_is_job_error(client):
    r = client.get("/api/fail/RUNTIME")
    assert r.status_code == 202
    body = _poll(client, r.json()["jobId"])
    assert body["state"] == "error" and body["result"] is None
    assert body["error"]["code"] == "INTERNAL" and "boom" in body["error"]["message"]
    r = client.get("/api/fail/API")
    body = _poll(client, r.json()["jobId"])
    assert body["error"] == {"code": "OUTSIDE_FEED", "message": "window outside every timetable"}


def test_api_error_inside_budget_is_plain_error(client):
    r = client.get("/api/fail/API", params={"budget": 3})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "OUTSIDE_FEED"


def test_unknown_job_404(client):
    r = client.get("/api/jobs/job_nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NO_SUCH_JOB"
