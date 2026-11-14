"""R21: does a published alert still hold after a new GTFS version takes effect?

Rows come from the published alerts' informedEntity (routeId, stopId, directionId);
for a closure that is not published yet, from its analysis stops in state "affected".
Each row is looked up in both versions: the stop, the route and the number of trips
of that route and direction that call at that stop.
"""

from __future__ import annotations

import math
from datetime import date

from app.common import gtfs, state
from app.common.errors import ApiError, not_found
from app.common.timeutil import parse_iso
from app.feedcheck import diff as fd
from app.feedcheck.models import FeedCheck, FeedCheckRow
from app.models.base import I18n

MOVED_METERS = 25.0


def _closure(closure_id: str) -> dict:
    try:
        c = state.read("closures", closure_id)
    except ValueError:
        c = None
    if c is None:
        raise not_found(f"No closure {closure_id}.")
    return c


def _entities(closure_id: str) -> tuple[list[tuple[str, str | None, int | None]], str | None]:
    """((routeId, stopId, directionId) rows, the window end) of the closure's alerts."""
    pub = state.read("published", closure_id)
    ents: list[tuple[str, str | None, int | None]] = []
    end: str | None = None
    if pub:
        for a in pub.get("alerts", []):
            for e in a.get("informedEntity", []):
                if e.get("routeId"):
                    ents.append((e["routeId"], e.get("stopId"), e.get("directionId")))
            for p in a.get("activePeriod", []):
                if p.get("end") and (end is None or parse_iso(p["end"]) > parse_iso(end)):
                    end = p["end"]
    else:
        an = state.read("closures", closure_id, "analysis") or {}
        for s in an.get("stops", []):
            if s.get("state") == "affected" and s.get("routeId"):
                ents.append((s["routeId"], s.get("stopId"), s.get("directionId")))
    seen: set = set()
    uniq = [e for e in ents if not (e in seen or seen.add(e))]
    return uniq, end


def _meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dy = (lat2 - lat1) * 111_320.0
    dx = (lon2 - lon1) * 111_320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def _calls(pat, route: str, direction: int | None, stop: str) -> int:
    if direction is not None:
        return int(pat.get((route, direction, stop), 0))
    return int(sum(pat.get((route, d, stop), 0) for d in (0, 1)))


def _fmt(d: str | None) -> str:
    if not d:
        return "data necunoscută"
    y, m, dd = d.split("-")
    return f"{dd}.{m}.{y}"


def feed_check(closure_id: str, version: str | None = None) -> FeedCheck:
    closure = _closure(closure_id)
    base_v, target_v = fd.default_pair()
    if version:
        target_v = version
    a, b = fd.load(base_v), fd.load(target_v)
    ents, alert_end = _entities(closure_id)
    if not ents:
        raise ApiError(409, "NO_ALERT_ROWS", f"Closure {closure_id} has no published alerts or affected stops to check.")
    pa, pb = fd.patterns(a), fd.patterns(b)
    names_a = dict(zip(a.stops.stop_id, a.stops.stop_name))
    pos_a = {r.stop_id: (float(r.stop_lat), float(r.stop_lon)) for r in a.stops.itertuples()}
    names_b = dict(zip(b.stops.stop_id, b.stops.stop_name))
    pos_b = {r.stop_id: (float(r.stop_lat), float(r.stop_lon)) for r in b.stops.itertuples()}
    routes_b = set(b.routes.route_id)
    rows: list[FeedCheckRow] = []
    for route, stop, direction in ents:
        if stop is None:
            continue
        name = names_a.get(stop) or names_b.get(stop) or ""
        before, after = _calls(pa, route, direction, stop), _calls(pb, route, direction, stop)
        if stop not in names_b:
            status = "stop_missing"
        elif route not in routes_b:
            status = "route_missing"
        elif before > 0 and after == 0:
            status = "not_served"
        elif before == 0 and after > 0:
            status = "now_served"
        elif names_a.get(stop) and names_a[stop] != names_b[stop]:
            status = "renamed"
        elif stop in pos_a and _meters(*pos_a[stop], *pos_b[stop]) > MOVED_METERS:
            status = "moved"
        else:
            status = "ok"
        rows.append(FeedCheckRow(stopId=stop, name=name, routeId=route, directionId=direction,
                                 status=status, tripsBase=before, tripsTarget=after))
    window_end = alert_end or (closure.get("window") or {}).get("end")
    effect = b.start
    applies = True
    if effect and window_end:
        applies = parse_iso(window_end).date() >= effect
    bad = [r for r in rows if r.status in ("stop_missing", "route_missing", "not_served")]
    soft = [r for r in rows if r.status in ("now_served", "renamed", "moved")]
    if not applies:
        verdict = "not_applicable"
    elif bad:
        verdict = "republish"
    elif soft:
        verdict = "check"
    else:
        verdict = "valid"

    when = _fmt(effect.isoformat() if effect else None)
    when_en = effect.strftime("%d %b %Y") if effect else "an unknown date"
    first = (bad or soft)[:3]
    listing = "; ".join(f"{r.name or r.stopId} ({r.stopId}, linia {r.routeId})" for r in first)
    more = len(bad or soft) - len(first)
    if more > 0:
        listing += f" și încă {more}"
    if verdict == "not_applicable":
        summary = I18n(ro=f"Orarul {target_v} intră în vigoare pe {when}; anunțul se încheie pe {_fmt(window_end and window_end[:10])}, deci nu e afectat.",
                       en=f"Timetable {target_v} takes effect on {when_en}; the notice ends before, so it is not affected.")
    elif verdict == "valid":
        summary = I18n(ro=f"Orarul {target_v} intră în vigoare pe {when}: anunțul rămâne valabil.",
                       en=f"Timetable {target_v} takes effect on {when_en}: the notice stays valid.")
    elif verdict == "republish":
        summary = I18n(ro=f"Orarul {target_v} intră în vigoare pe {when}: de verificat, nu mai apare în orar: {listing}. Anunțul trebuie republicat.",
                       en=f"Timetable {target_v} takes effect on {when_en}: to check, no longer in the timetable: {len(bad)} stop/line pair(s). The notice must be republished.")
    else:
        summary = I18n(ro=f"Orarul {target_v} intră în vigoare pe {when}: de verificat, stație servită din nou sau cu alt nume sau altă poziție: {listing}.",
                       en=f"Timetable {target_v} takes effect on {when_en}: to check, served again or renamed or moved on {len(soft)} stop/line pair(s).")
    draft = None
    if verdict in ("republish", "check"):
        draft = I18n(
            ro=(f"De la {when} se aplică orarul {target_v}. Față de {base_v}, în orar diferă: {listing}. "
                "Anunțul se republică după verificarea cu SMTT."),
            en=None,
        )
    d = fd.diff_versions(base_v, target_v)
    counts = d.model_copy(update={"stopsAdded": [], "stopsRemoved": d.stopsRemoved[:20], "tripsByRoute": [], "serviceDays": d.serviceDays[:10]})
    return FeedCheck(
        closureId=closure_id,
        base=d.base,
        target=d.target,
        takesEffectOn=effect.isoformat() if effect else None,
        windowEnd=window_end,
        applies=applies,
        verdict=verdict,
        rows=rows,
        summary=summary,
        draftNotice=draft,
        diff=counts,
        provenance=[a.provenance, b.provenance],
    )
