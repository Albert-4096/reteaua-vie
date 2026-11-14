"""R10: the bus keeps one lane through the works (a variant; the default impact is untouched).

For the chosen bus and trolleybus lines of a closure the analysis rows are dropped (their stops stay
served), and so are the notice's route actions for them, then the impact is computed again with
the existing `impact.build_impact`. Trams are excluded. Whether a lane can stay open is judged only
from OSM `lanes`/`width` and the GTFS tram shapes (street_judge); when it cannot be judged the rows
stay lost and the note says „nu se poate judeca din date”. A person who has confirmed the lane
(`lanesConfirmed`) skips the OSM judgement and the note says so. The lane's real width is always for
the builder to confirm.
"""

from __future__ import annotations

import copy

from app.common import state
from app.common.city import load_network, route_mode
from app.common.errors import invalid, not_found
from app.m1_disruption import impact as imp
from app.m4_access import street_judge as sj
from app.models.base import I18n
from app.models.v2 import (ScenarioNote, TransitThrough, TransitThroughExcluded, TransitThroughKept,
                           TransitThroughStreet, TransitThroughTotals)

BUS = ("bus", "trolleybus")


def _mode(route_id: str) -> str:
    r = load_network().route_by_id.get(route_id) or {}
    return route_mode(route_id, r.get("type"))


def select(rows: list[dict], route_ids: list[str]) -> tuple[list[str], list[TransitThroughExcluded]]:
    """(routes that can keep a lane, excluded routes with the reason), among the routes with lost rows."""
    lost = sorted({r["routeId"] for r in rows if imp.counts_as_lost(r)})
    wanted = [r for r in (route_ids or lost)]
    unknown = [r for r in wanted if r not in load_network().route_by_id]
    if unknown:
        raise invalid(f"Unknown route {unknown[0]}.")
    kept, excl = [], []
    for r in wanted:
        if r not in lost:
            continue
        if _mode(r) in BUS:
            kept.append(r)
        else:
            excl.append(TransitThroughExcluded(routeId=r, reason=I18n(
                ro="linie de tramvai: nu se poate judeca din date; șinele sunt lucrarea",
                en="tram line: cannot be judged from the data; the tracks are the works")))
    return kept, excl


def _name(route_id: str) -> str:
    return (load_network().route_by_id.get(route_id) or {}).get("shortName", route_id)


def apply(closure: dict, rows: list[dict], m) -> tuple[dict, list[dict], ScenarioNote]:
    """(closure copy, rows, note) for a `transit_through` mitigation. Rows stay lost when the street cannot be judged."""
    kept, excl = select(rows, list(m.routeIds))
    if m.lanesConfirmed:
        ok, reasons = True, []
    elif not closure.get("geometry"):
        ok, reasons = False, [I18n(ro="lucrarea nu are geometrie", en="the closure has no geometry")]
    else:
        ok, _streets, reasons = sj.verdict(closure)
    ex_ro = "; ".join(f"linia {_name(e.routeId)}: {e.reason.ro}" for e in excl)
    ex_en = "; ".join(f"line {_name(e.routeId)}: {e.reason.en}" for e in excl)
    if not ok or not kept:
        why_ro = "; ".join(r.ro for r in reasons) or "nicio linie de autobuz sau troleibuz în lucrare"
        why_en = "; ".join(r.en for r in reasons) or "no bus or trolleybus line in the closure"
        note = ScenarioNote(kind="transit_through", text=I18n(
            ro=f"Banda rămasă pentru autobuz: nu se poate judeca din date ({why_ro}). Stațiile rămân fără serviciu."
               + (f" {ex_ro}." if ex_ro else ""),
            en=f"Bus keeps one lane: cannot be judged from the data ({why_en}). The stops stay without service."
               + (f" {ex_en}." if ex_en else "")))
        return closure, rows, note
    c = copy.deepcopy(closure)
    for key in ("routeActions", "temporaryRoutes"):
        if c.get(key):
            c[key] = [a for a in c[key] if a.get("routeId") not in kept] or None
    dropped = [r for r in rows if r["routeId"] in kept and imp.counts_as_lost(r)]
    new_rows = [r for r in rows if r["routeId"] not in kept]
    n = sum(r.get("departuresLost") or 0 for r in dropped)
    lines = ", ".join(_name(r) for r in kept)
    who_ro = "lățime confirmată de un om" if m.lanesConfirmed else "bandă judecată din OSM"
    who_en = "lane confirmed by a person" if m.lanesConfirmed else "lane judged from OSM"
    note = ScenarioNote(kind="transit_through", value=float(n), unit="plecări", text=I18n(
        ro=f"Linia {lines} trece pe banda rămasă ({who_ro}): +{n} plecări păstrate · 0 km de ocolire "
           f"(de confirmat cu constructorul: lățimea benzii)." + (f" {ex_ro}." if ex_ro else ""),
        en=f"Line {lines} uses the remaining lane ({who_en}): +{n} departures kept · 0 km of detour "
           f"(to confirm with the builder: lane width)." + (f" {ex_en}." if ex_en else "")))
    return c, new_rows, note


def _totals(i) -> TransitThroughTotals:
    t = i.totals
    return TransitThroughTotals(stopsSuspended=t.stopsSuspended, departuresLost=t.departuresLost,
                                residentsLosingStop=t.residentsLosingStop)


def transit_through(closure_id: str, route_ids: list[str], lanes_confirmed: bool = False) -> TransitThrough:
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id}.")
    analysis = state.read("closures", closure_id, state.PART_ANALYSIS)
    if analysis is None:
        raise not_found(f"Closure {closure_id} was never analyzed.", code="NOT_ANALYZED")
    rows = analysis["stops"]
    full = imp.build_impact(closure, rows)
    kept, excl = select(rows, route_ids)

    class _M:  # the mitigation without building a scenario
        routeIds = route_ids
        lanesConfirmed = lanes_confirmed

    c2, rows2, note = apply(closure, rows, _M)
    applied = rows2 is not rows
    variant = imp.build_impact(c2, rows2) if applied else full
    streets: list[TransitThroughStreet] = []
    reasons: list[I18n] = []
    if closure.get("geometry") and not lanes_confirmed:
        _ok, js, reasons = sj.verdict(closure)
        streets = [TransitThroughStreet(osmId=s.osm_id, name=s.name, lanes=s.lanes, width=s.width, oneway=s.oneway,
                                        enough=s.enough) for s in js]
    ft, vt = full.totals, variant.totals
    dep = None if ft.departuresLost is None or vt.departuresLost is None else ft.departuresLost - vt.departuresLost
    res = None if ft.residentsLosingStop is None or vt.residentsLosingStop is None else ft.residentsLosingStop - vt.residentsLosingStop
    return TransitThrough(
        closureId=closure_id, verdict="applied" if applied else "cannot_judge", reasons=reasons, streets=streets,
        keptRoutes=kept if applied else [], excludedRoutes=excl, full=_totals(full), variant=_totals(variant),
        kept=TransitThroughKept(stops=ft.stopsSuspended - vt.stopsSuspended, departures=dep, residentsKeepingStop=res),
        note=note.text, provenance=list(full.provenance))
