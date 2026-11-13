"""POST /api/closures/parse: a pasted STPT notice -> a saved draft Closure + the sentences not read.

Deterministic, no LLM (SPEC §6.1 item 3). The draft is stored like any other closure, so the
frontend continues with POST /api/closures/{id}/analyze.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import Field

from app.common import state
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


def parse_and_save(text: str) -> ParseResult:
    result = parser.parse_notice(text)
    data = result.closure.model_dump(mode="json", by_alias=True)
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
