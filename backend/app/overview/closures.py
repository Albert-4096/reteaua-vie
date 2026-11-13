"""ClosureSummary rows from the state store (calendar and map list).

Numbers come from the closure's stored Impact (part "impact"); a closure that
has none yet shows null ("necunoscut"), never 0.
"""

from __future__ import annotations

from datetime import datetime

from app.common import state
from app.common.city import zones_for_geometry
from app.common.geo import buffer_m, from_geojson
from app.common.timeutil import parse_iso
from app.models.v2 import ClosureSummary


def _route_ids(closure: dict, analysis: dict | None) -> list[str]:
    ids: list[str] = []
    if analysis:
        ids += [r["routeId"] for r in analysis.get("routes") or []]
    ids += closure.get("routeIds") or []
    ids += [a["routeId"] for a in closure.get("routeActions") or []]
    return list(dict.fromkeys(ids))


def _zone_slugs(closure: dict, impact: dict | None, analysis: dict | None) -> list[str]:
    if impact and impact.get("byZone"):
        return [z["slug"] for z in impact["byZone"]]
    slugs: list[str] = []
    if analysis:
        slugs += [s["zoneSlug"] for s in analysis.get("stops") or [] if s.get("zoneSlug")]
    if not slugs and closure.get("geometry"):
        try:
            geom = buffer_m(from_geojson(closure["geometry"]), float(closure.get("bufferMeters") or 30))
            slugs = zones_for_geometry(geom)
        except Exception:  # a broken geometry must not break the list
            slugs = []
    return sorted(set(slugs))


def summarize(closure: dict) -> ClosureSummary:
    cid = closure["id"]
    impact = state.read("closures", cid, state.PART_IMPACT)
    analysis = state.read("closures", cid, state.PART_ANALYSIS)
    published = state.read("published", cid)
    totals = (impact or {}).get("totals") or {}
    return ClosureSummary(
        id=cid,
        title=closure["title"],
        status=closure["status"],
        window=closure["window"],
        routeIds=_route_ids(closure, analysis),
        zoneSlugs=_zone_slugs(closure, impact, analysis),
        stopsSuspended=totals.get("stopsSuspended"),
        departuresLost=totals.get("departuresLost"),
        publishedAt=(published or {}).get("publishedAt"),
        reconstructed=True if (published or {}).get("reconstructed") else None,
        reconstructedNote=(published or {}).get("reconstructedNote") if (published or {}).get("reconstructed")
        else None,
    )


def list_summaries(start: datetime | None = None, end: datetime | None = None,
                   status: str | None = None) -> list[ClosureSummary]:
    """Closures whose window overlaps [start, end), optionally of one status, by start time."""
    rows = []
    for c in state.list_all("closures"):
        if status and c.get("status") != status:
            continue
        ws, we = parse_iso(c["window"]["start"]), parse_iso(c["window"]["end"])
        if start is not None and we <= start:
            continue
        if end is not None and ws >= end:
            continue
        rows.append((ws, summarize(c)))
    rows.sort(key=lambda r: (r[0], r[1].id))
    return [r[1] for r in rows]
