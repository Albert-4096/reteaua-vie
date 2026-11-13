"""GET /api/jobs/{jobId}: the state of a slow computation (CONTRACT `Job`)."""

from __future__ import annotations

from fastapi import APIRouter

from app.common.errors import not_found
from app.common.jobs import get_job
from app.models.v2 import Job

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=Job)
def job(job_id: str) -> Job:
    found = get_job(job_id)
    if found is None:
        raise not_found(f"No job {job_id!r} (unknown, or the server restarted before it finished).", "NO_SUCH_JOB")
    return found
