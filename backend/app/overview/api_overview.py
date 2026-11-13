"""Step 0 endpoints that serve data we already hold (D-011):
/api/health, /api/network, /api/zones, /api/cases, /api/closures (list).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query

from app.cases.catalog import case_summaries
from app.common import gtfs
from app.common.city import load_network, load_parking, load_zones, network_payload
from app.common.errors import invalid
from app.common.timeutil import iso, parse_iso
from app.config import get_settings
from app.models.v1 import CaseSummary, Health, Network, ZoneCollection
from app.models.v2 import ClosureSummary
from app.overview.closures import list_summaries

router = APIRouter(tags=["overview"])

STATUSES = ("draft", "analyzed", "published")


@router.get("/health", response_model=Health)
def health() -> Health:
    s = get_settings()
    feed_version = None
    fetched: list[datetime] = []
    ok = True
    try:
        net = load_network()
        feed_version = net.feed_version
        fetched.append(parse_iso(net.provenance.fetchedAt))
        fetched.append(parse_iso(load_zones().provenance.fetchedAt))
        fetched.append(parse_iso(load_parking().provenance.fetchedAt))
    except Exception:
        ok = False
    g = gtfs.feed_file_time()
    if g is not None:
        fetched.append(g)
    newest = max(fetched) if fetched else None
    return Health(
        ok=ok,
        feedVersion=feed_version,
        dataFetchedAt=iso(newest) if newest else None,
        # With DATA_FREEZE=1 no source is refreshed: the data is frozen as of its newest file.
        dataFrozenAt=iso(newest) if (s.data_freeze and newest) else None,
        demoNow=iso(s.demo_now) if s.demo_now else None,
        modulesFailed=_modules_failed(),
    )


def _modules_failed() -> list[str]:
    """api modules that main.py skipped because they failed to import."""
    import sys

    main = sys.modules.get("app.main")
    return list(getattr(main, "MODULES_FAILED", []))


@router.get("/network", response_model=Network)
def network() -> dict:
    return network_payload()


@router.get("/zones", response_model=ZoneCollection)
def zones() -> dict:
    z = load_zones()
    return {**z.collection, "provenance": [z.provenance.model_dump()]}


@router.get("/cases", response_model=list[CaseSummary])
def cases() -> list[CaseSummary]:
    return case_summaries()


def _opt_time(value: str | None, name: str) -> datetime | None:
    if not value:
        return None
    try:
        return parse_iso(value)
    except ValueError:
        raise invalid(f"`{name}` must be an ISO 8601 time, e.g. 2026-11-08T10:00:00+02:00")


@router.get("/closures", response_model=list[ClosureSummary])
def closures(
    from_: str | None = Query(None, alias="from", description="ISO time; closures ending after it"),
    to: str | None = Query(None, description="ISO time; closures starting before it"),
    status: str | None = Query(None, description="draft | analyzed | published"),
) -> list[ClosureSummary]:
    if status and status not in STATUSES:
        raise invalid(f"`status` must be one of {', '.join(STATUSES)}")
    return list_summaries(_opt_time(from_, "from"), _opt_time(to, "to"), status or None)

