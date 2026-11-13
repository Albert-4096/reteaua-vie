"""GET /api/closures/{id}/access: residents who lose access to a hospital / school / rail station (M4, job)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from app.common.jobs import closure_fingerprint, respond
from app.m4_access import access, patched_gtfs
from app.models.v2 import AccessImpact, JobAccepted

router = APIRouter(tags=["m4-access"])


def access_key(closure_id: str, dest: str, minutes: int) -> str:
    return f"access:v{access.ACCESS_VERSION}:{closure_id}:{dest}:{minutes}:{closure_fingerprint(closure_id)}"


@router.get("/closures/{closure_id}/access", response_model=AccessImpact,
            responses={202: {"model": JobAccepted, "description": "Still computing: poll GET /api/jobs/{jobId}"}})
def closure_access(closure_id: str,
                   dest: Literal["hospital", "school", "rail_station"] = Query("hospital"),
                   minutes: int = Query(30, ge=15, le=60)):
    patched_gtfs.lost_rows(closure_id)  # 404 / NOT_ANALYZED before starting a job
    return respond(access_key(closure_id, dest, minutes), lambda: access.compute_access(closure_id, dest, minutes))
