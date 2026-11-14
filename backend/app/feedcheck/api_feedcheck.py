"""R21 endpoints: GTFS version diff and the published-alert check (CONTRACT v2.12)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.feedcheck import check, diff
from app.feedcheck.models import FeedCheck, FeedDiff

router = APIRouter(tags=["R21 feed check"])


@router.get("/feed-diff", response_model=FeedDiff)
def feed_diff(
    from_: str | None = Query(None, alias="from", description="base feed_version, default: in force at the app clock"),
    to: str | None = Query(None, description="target feed_version, default: the next newer one on disk"),
) -> FeedDiff:
    base, target = diff.default_pair()
    return diff.diff_versions(from_ or base, to or target)


@router.get("/closures/{closure_id}/feed-check", response_model=FeedCheck)
def feed_check(closure_id: str, version: str | None = Query(None, description="target feed_version")) -> FeedCheck:
    return check.feed_check(closure_id, version)
