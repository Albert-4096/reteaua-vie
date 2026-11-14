"""POST /api/closures/parse: a pasted STPT notice -> a saved draft Closure + the sentences not read.

Deterministic, no LLM (SPEC §6.1 item 3). The draft is stored like any other closure, so the
frontend continues with POST /api/closures/{id}/analyze.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from fastapi import APIRouter
from pydantic import Field

from app.common import state, stpt_posts
from app.common.errors import invalid
from app.config import now
from app.common.timeutil import iso
from app.m1_disruption import parser
from app.models.base import Model
from app.models.v1 import Closure, ParseResult

router = APIRouter(tags=["M1 closures"])

MAX_TEXT = 20_000


class ParseInput(Model):
    text: str = Field(description="The notice as pasted (Romanian plain text).")


SAME_NOTICE = 0.9   # share of words in common with a recorded notice (copy from the web page vs the API text)


def recorded_post(text: str) -> stpt_posts.StptPost | None:
    """The recorded STPT notice the pasted text is a copy of, or None.

    A pasted notice says „de mâine” or „luni”: those are read from the day it was posted, not from
    today, so a notice from September is not read as a closure starting tomorrow."""
    words = parser.norm(text).split()
    if len(words) < 12:
        return None
    best, best_ratio = None, SAME_NOTICE
    for post in stpt_posts.load_posts().values():
        other = parser.norm(post.text).split()
        sm = SequenceMatcher(None, words, other, autojunk=False)
        if sm.real_quick_ratio() < best_ratio or sm.quick_ratio() < best_ratio:
            continue
        r = sm.ratio()
        if r >= best_ratio:
            best, best_ratio = post, r
    return best


def parse_and_save(text: str) -> ParseResult:
    post = recorded_post(text)
    result = parser.parse_notice(text, reference=post.date if post else None)
    data = result.closure.model_dump(mode="json", by_alias=True)
    if post is not None and not data.get("sourceUrl"):
        data["sourceUrl"] = post.link or None
    if data.get("geometry") is None and data.get("routeActions"):
        # same fallback as input by line: the route path along the suspended stops
        from app.m1_disruption import matching

        try:
            data["geometry"] = matching.geometry_from_actions(data["routeActions"])
        except Exception:
            data["geometry"] = None
    data.update(id=state.new_id("cl"), status="draft", createdAt=iso(now()))
    closure = Closure.model_validate(data)
    state.write("closures", closure.id, closure)
    return ParseResult(closure=closure, unread=result.unread)


@router.post("/closures/parse", response_model=ParseResult, status_code=201)
def parse_notice(body: ParseInput) -> ParseResult:
    text = (body.text or "").strip()
    if not text:
        raise invalid("text is empty: paste the notice text.")
    if len(text) > MAX_TEXT:
        raise invalid(f"text is too long ({len(text)} characters, at most {MAX_TEXT}).")
    return parse_and_save(text)
