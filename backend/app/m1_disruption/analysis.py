"""Analysis of a closure: affected (stop, route, direction) rows (SPEC §6.1 items 4-7).

    analyze_closure(closure) -> Analysis     match + fill departures and nearest served stop;
                                             stored (part "analysis") when the closure is stored,
                                             and the closure becomes `analyzed`
    get_analysis(closure_id) -> Analysis | None   the stored one, no recompute
    apply_decisions(closure_id, decisions) -> Analysis   human confirm (PATCH .../stops)

Decisions live in the state part "decisions" and survive a re-analysis:
{"decisions": {"<stop>|<route>|<dir>": bool}, "log": [...]}. Unticking an
`affected` row is logged as an override.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from app.common import gtfs, state
from app.common import provenance as prov
from app.common.city import load_network
from app.common.errors import conflict, invalid, not_found
from app.common.timeutil import iso, parse_iso
from app.config import now
from app.m1_disruption import impact as imp
from app.m1_disruption import matching
from app.models.v1 import Analysis, AnalysisRoute, Closure

PART_DECISIONS = "decisions"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")


def _key_str(stop_id: str, route_id: str, direction_id: int) -> str:
    return f"{stop_id}|{route_id}|{int(direction_id)}"


def _as_dict(closure: Closure | dict) -> dict:
    if isinstance(closure, Closure):
        return closure.model_dump(mode="json", by_alias=True)
    return dict(closure)


def _stored_decisions(closure_id: str) -> dict[str, bool]:
    try:
        data = state.read("closures", closure_id, PART_DECISIONS)
    except ValueError:
        return {}
    return dict((data or {}).get("decisions") or {})


def _order_rows(rows: list[dict], tt: imp.Timetable) -> list[dict]:
    pos: dict[tuple[str, int], dict[str, int]] = {}

    def rank(r: dict) -> tuple:
        k = (r["routeId"], r["directionId"])
        if k not in pos:
            pos[k] = {s: i for i, s in enumerate(tt.stop_order(*k))}
        return (r["routeShortName"].zfill(4), r["routeId"], r["directionId"], pos[k].get(r["stopId"], 999))

    return sorted(rows, key=rank)


def enrich(closure: dict, rows: list[dict]) -> tuple[list[dict], list[Any]]:
    """Fill departuresLost and nearestServed on every row. Returns (rows, provenance)."""
    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    tt = imp.timetable_for(start)
    cw = imp.count_window(start, end, tt)
    counts = imp.departure_counts(cw, tt)
    lost = {imp.row_key(r) for r in rows if imp.counts_as_lost(r)}
    svc = imp.ServiceState.build(counts, lost)
    stats = imp.NearestStats()
    for r in rows:
        r["departuresLost"] = None if counts is None else int(counts.get(imp.row_key(r), 0))
        r["nearestServed"] = imp.nearest_served(r, svc, stats)
    provenance = [imp.timetable_provenance(tt, cw), load_network().provenance,
                  imp.osm_provenance(imp.walking_note(stats))]
    return rows, provenance


def _feed_version(closure: dict) -> str:
    tt = imp.timetable_for_closure(closure)
    if tt.history:
        return tt.version or ""
    return load_network().feed_version or (tt.version or "")


def _routes(rows: list[dict]) -> list[AnalysisRoute]:
    n = load_network()
    out: dict[str, dict] = {}
    for r in rows:
        e = out.setdefault(r["routeId"], {"dirs": set(), "stops": set()})
        e["dirs"].add(r["directionId"])
        if r.get("confirmed") is not False:
            e["stops"].add(r["stopId"])
    res = []
    for rid, e in out.items():
        route = n.route_by_id.get(rid, {})
        res.append(AnalysisRoute(routeId=rid, shortName=route.get("shortName", rid), type=int(route.get("type", 3)),
                                 directionIds=sorted(e["dirs"]), stopsAffected=len(e["stops"])))
    return sorted(res, key=lambda a: (a.shortName.zfill(4), a.routeId))


def _build(closure: dict, rows: list[dict], extra_provenance: Iterable[Any] = ()) -> Analysis:
    rows, provenance = enrich(closure, rows)
    rows = _order_rows(rows, imp.timetable_for_closure(closure))
    unsure = sum(1 for r in rows if r["state"] == "unsure" and r.get("confirmed") is None)
    return Analysis(
        closureId=closure["id"],
        feedVersion=_feed_version(closure),
        stops=rows,
        routes=_routes(rows),
        unsureCount=unsure,
        provenance=[*provenance, *extra_provenance],
    )


def _apply(rows: list[dict], decisions: dict[str, bool]) -> None:
    for r in rows:
        r["confirmed"] = decisions.get(_key_str(r["stopId"], r["routeId"], r["directionId"]))


def analyze_closure(closure: Closure | dict) -> Analysis:
    """Match the closure, apply stored decisions, fill departures and nearest served stops.

    When the closure is in the state store, the Analysis is stored and the
    closure status becomes `analyzed` (a published closure keeps `published`).
    """
    c = _as_dict(closure)
    rows, unresolved = matching.match_closure(c)
    stored = bool(_ID_RE.match(c.get("id") or "")) and state.exists("closures", c["id"])
    _apply(rows, _stored_decisions(c["id"]) if stored else {})
    extra = []
    if unresolved:
        extra.append(prov.provenance(
            "Rețeaua Vie, potrivirea numelor de stații / stop-name matching", now(), None, None,
            "Nume negăsite în GTFS (verificați anunțul): " + ", ".join(unresolved)))
    analysis = _build(c, rows, extra)
    if stored:
        state.write("closures", c["id"], analysis, part=state.PART_ANALYSIS)

        def _status(old: dict | None) -> dict | None:
            if old is None:
                return old
            if old.get("status") != "published":
                old["status"] = "analyzed"
            return old

        state.update("closures", c["id"], _status)
    return analysis


def get_analysis(closure_id: str) -> Analysis | None:
    """The stored Analysis (decisions applied), or None if never analyzed."""
    try:
        data = state.read("closures", closure_id, state.PART_ANALYSIS)
    except ValueError:
        return None
    return Analysis.model_validate(data) if data is not None else None


def apply_decisions(closure_id: str, decisions: list[dict]) -> Analysis:
    """Human confirm: decisions keyed by (stopId, routeId, directionId)."""
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id}.")
    if closure.get("status") == "published":
        raise conflict(f"Closure {closure_id} is already published.", code="ALREADY_PUBLISHED")
    current = get_analysis(closure_id)
    if current is None:
        raise not_found(f"Closure {closure_id} was never analyzed.", code="NOT_ANALYZED")
    rows = [s.model_dump(mode="json") for s in current.stops]
    by_key = {_key_str(r["stopId"], r["routeId"], r["directionId"]): r for r in rows}
    unknown = [d for d in decisions if _key_str(d["stopId"], d["routeId"], d["directionId"]) not in by_key]
    if unknown:
        names = ", ".join(_key_str(d["stopId"], d["routeId"], d["directionId"]) for d in unknown[:5])
        raise invalid(f"No analysis row for: {names}.", code="UNKNOWN_STOP_ROW")
    at = iso(now())

    def _update(old: dict | None) -> dict:
        data = old or {"decisions": {}, "log": []}
        for d in decisions:
            k = _key_str(d["stopId"], d["routeId"], d["directionId"])
            row = by_key[k]
            previous = data["decisions"].get(k)
            data["decisions"][k] = bool(d["confirmed"])
            data["log"].append({
                "at": at, "stopId": d["stopId"], "routeId": d["routeId"], "directionId": int(d["directionId"]),
                "state": row["state"], "confidence": row["confidence"], "previous": previous,
                "confirmed": bool(d["confirmed"]),
                "override": row["state"] == "affected" and not d["confirmed"],
            })
        return data

    stored = state.update("closures", closure_id, _update, part=PART_DECISIONS)
    _apply(rows, stored["decisions"])
    extra = [p for p in current.provenance if p.source.startswith("Rețeaua Vie, potrivirea")]
    analysis = _build(closure, rows, extra)
    state.write("closures", closure_id, analysis, part=state.PART_ANALYSIS)
    return analysis


def overrides(closure_id: str) -> list[dict]:
    """Logged overrides (affected rows a person unticked), oldest first."""
    data = state.read("closures", closure_id, PART_DECISIONS) or {}
    return [e for e in data.get("log") or [] if e.get("override")]
