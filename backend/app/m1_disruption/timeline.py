"""R15-B: a closure's lifecycle (anunțat → publicat → în desfășurare → încheiat) and the notice lead time.

Each step takes its time from a source, never from a guess:
  - anunțat: the STPT post's publication time (the recorded post whose link is the closure's
    sourceUrl, or the prepared case's post);
  - publicat: our publish record (state/published/<id>.json);
  - în desfășurare / încheiat: the closure's window.
Lead time = post time → works start, in hours (negative = the notice came after the start).
"""

from __future__ import annotations

from datetime import datetime

from app.common import state
from app.common.stpt_posts import StptPost, get_post, load_posts
from app.common.timeutil import iso, parse_iso
from app.config import now
from app.models.base import I18n
from app.models.v1 import ClosureTimeline, TimelineStep

STEPS = (
    ("anuntat", "Anunțat", "Announced"),
    ("publicat", "Publicat", "Published"),
    ("in_desfasurare", "În desfășurare", "Under way"),
    ("incheiat", "Încheiat", "Ended"),
)


def post_for(closure: dict) -> StptPost | None:
    """The recorded STPT post a closure comes from: its sourceUrl, else the prepared case's post."""
    url = closure.get("sourceUrl")
    if url:
        for post in load_posts().values():
            if post.link and post.link.rstrip("/") == url.rstrip("/"):
                return post
    from app.cases.catalog import CASES_BY_CLOSURE

    case = CASES_BY_CLOSURE.get(closure.get("id") or "")
    return get_post(case.post_id) if case else None


def _end_source(end: str | None) -> str | None:
    if not end:
        return None
    from app.m1_disruption.parser import open_end_default

    if parse_iso(end) == open_end_default():
        return ("anunțul nu dă o dată de încheiere: sfârșitul orarului GTFS / "
                "the notice gives no end date: the end of the GTFS timetable")
    return "fereastra lucrării / the works window"


def lead_hours(posted: datetime, start: str | datetime) -> float:
    s = parse_iso(start) if isinstance(start, str) else start
    return round((s - posted).total_seconds() / 3600, 1)


def timeline(closure: dict, at: datetime | None = None) -> ClosureTimeline:
    t = at or now()
    post = post_for(closure)
    try:
        pub = state.read("published", closure["id"]) or {}
    except (ValueError, KeyError):
        pub = {}
    window = closure.get("window") or {}
    sources = {
        "anuntat": (iso(post.date) if post else None, f"STPT, anunț {post.id} (stpt.ro)" if post else None),
        "publicat": (pub.get("publishedAt"),
                     ("reconstituit din anunțul STPT / reconstructed from the STPT notice" if pub.get("reconstructed")
                      else "Rețeaua Vie, feed GTFS-RT") if pub.get("publishedAt") else None),
        "in_desfasurare": (window.get("start"), "fereastra lucrării / the works window" if window.get("start") else None),
        "incheiat": (window.get("end"), _end_source(window.get("end"))),
    }
    steps, current = [], None
    for key, ro, en in STEPS:
        when, source = sources[key]
        done = bool(when) and parse_iso(when) <= t
        if done:
            current = key
        steps.append(TimelineStep(step=key, label=I18n(ro=ro, en=en), at=when, source=source, done=done))
    lead = lead_hours(post.date, window["start"]) if post and window.get("start") else None
    return ClosureTimeline(steps=steps, current=current, leadHours=lead, noticeUrl=post.link if post else None)
