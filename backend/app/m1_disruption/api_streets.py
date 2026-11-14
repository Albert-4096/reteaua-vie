"""R1-B: GET /api/streets?q= and GET /api/streets/{streetId}/section?from=&to= (step 1, „Stradă”)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.m1_disruption import streets
from app.m1_disruption.streets import StreetSearch, StreetSection

router = APIRouter(tags=["M1 closures"])


@router.get("/streets", response_model=StreetSearch)
def search_streets(q: str = Query(..., description="street name, ignoring case, diacritics and „str.”/„bd.”"),
                   limit: int = Query(streets.LIMIT, ge=1, le=50)) -> StreetSearch:
    """Streets of the City Hall register by current or former name, best match first."""
    return streets.search(q, limit)


@router.get("/streets/{street_id}/section", response_model=StreetSection)
def street_section(street_id: str,
                   from_: str | None = Query(None, alias="from", description="first click, „lon,lat”"),
                   to: str | None = Query(None, description="second click, „lon,lat”")) -> StreetSection:
    """The street between two clicks, as the geometry for POST /api/closures (kind „drawn”); no clicks = whole street."""
    return streets.section(street_id, streets.parse_point(from_, "from"), streets.parse_point(to, "to"))
