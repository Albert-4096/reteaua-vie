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
from app.common.city import load_network, route_mode
from app.common.errors import conflict, invalid, not_found
from app.common.timeutil import iso, parse_iso
from app.config import now
from app.m1_disruption import impact as imp
from app.m1_disruption import matching
from app.models.base import I18n
from app.models.v1 import Analysis, AnalysisRoute, Closure, DecisionGroup, StopRowKey

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
    svc = imp.ServiceState.build(counts, lost, {imp.row_key(r) for r in rows if imp.is_undecided(r)})
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


# --- decision groups: one question per line and cause instead of a checkbox per row ---------

_VEHICLE = {"tram": (("tramvaiul", "tramvaiele"), ("tram", "trams")),
            "bus": (("autobuzul", "autobuzele"), ("bus", "buses")),
            "trolleybus": (("troleibuzul", "troleibuzele"), ("trolleybus", "trolleybuses"))}
_MODE = {"tram": ("tramvai", "tram"), "bus": ("autobuz", "bus"), "trolleybus": ("troleibuz", "trolleybus")}
_REASON_TEXT = {
    "NOT_NAMED_IN_NOTICE": ("Anunțul nu numește aceste stații.", "The notice does not name these stops."),
    "ROUTE_NOT_IN_NOTICE": ("Anunțul nu numește linia.", "The notice does not name the line."),
    "DIRECTION_UNCLEAR": ("Sensul nu reiese din desen.", "The direction is unclear from the drawing."),
    "EDGE_OF_BUFFER": ("Stațiile sunt la marginea zonei închise.", "The stops are at the edge of the closed area."),
    "DUPLICATE_STOP_NAME": ("Mai multe stații poartă acest nume.", "Several stops share this name."),
}


def _lines(route_ids: Iterable[str], mode: str, lang: int) -> str:
    shorts = sorted({matching.route_short_name(r) for r in route_ids}, key=lambda s: (s.zfill(4), s))
    word = _VEHICLE[mode][lang][len(shorts) > 1]
    names = shorts[0] if len(shorts) == 1 else f"{', '.join(shorts[:-1])} {('și', 'and')[lang]} {shorts[-1]}"
    return f"{word} {names}"


def decision_groups(closure: dict, rows: list[dict]) -> list[DecisionGroup]:
    """Every `unsure` row in one group: same line, same reasons, same fact of the timetable (T2).

    The fact: every other line of the same mode that stops there loses the stop in this closure
    and no other line of that mode still stops there in the window, so this line cannot reach it
    either (suggested "affected"). Otherwise no suggestion: a person answers. Pure, data only.
    """
    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    tt = imp.timetable_for(start)
    counts = imp.departure_counts(imp.count_window(start, end, tt), tt)
    svc = imp.ServiceState.build(counts, {imp.row_key(r) for r in rows if imp.counts_as_lost(r)},
                                 {imp.row_key(r) for r in rows if imp.is_undecided(r)})
    lost_at: dict[str, set[str]] = {}
    for r in rows:
        if imp.counts_as_lost(r):
            lost_at.setdefault(r["stopId"], set()).add(r["routeId"])
    groups: dict[tuple, dict] = {}
    for r in rows:
        if r["state"] != "unsure":
            continue
        rid, mode = r["routeId"], route_mode(r["routeId"])
        others = {o for o in lost_at.get(r["stopId"], ()) if o != rid and route_mode(o) == mode}
        still = {o for o, _ in svc.served(r["stopId"]) if o != rid and route_mode(o) == mode}
        cut = bool(others) and not still
        g = groups.setdefault((rid, tuple(r["reasons"]), cut), {"rows": [], "others": set(), "still": set()})
        g["rows"].append(r)
        g["others"] |= others
        g["still"] |= still
    out: list[DecisionGroup] = []
    for (rid, reasons, cut), g in sorted(groups.items(), key=lambda kv: (kv[1]["rows"][0]["routeShortName"].zfill(4),
                                                                         kv[0][0], not kv[0][2])):
        gid = f"{rid}-{'lost' if cut else 'open'}"
        same = sum(1 for o in out if o.id == gid or o.id.startswith(gid + "-"))
        out.append(_group(closure, gid + (f"-{same + 1}" if same else ""), rid, reasons, cut, g))
    return out


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _group(closure: dict, gid: str, rid: str, reasons: tuple, cut: bool, g: dict) -> DecisionGroup:
    mode, rows = route_mode(rid), g["rows"]
    by_dir: dict[int, list[dict]] = {}
    for r in rows:
        by_dir.setdefault(r["directionId"], []).append(r)
    span = max(by_dir.values(), key=len)  # travel order of the direction with the most rows
    first, last = span[0]["name"], span[-1]["name"]
    line = [_lines([rid], mode, k) for k in (0, 1)]
    question = (I18n(ro=f"Oprește {line[0]} între {first} și {last}?", en=f"Does {line[1]} stop between {first} and {last}?")
                if first != last else I18n(ro=f"Oprește {line[0]} în stația {first}?", en=f"Does {line[1]} stop at {first}?"))
    names = next((a.get("stopNames") for a in closure.get("routeActions") or []
                  if a["routeId"] == rid and a.get("stopNames")), None)
    parts: list[tuple[str, str]] = []
    if "NOT_NAMED_IN_NOTICE" in reasons and names:
        short = matching.route_short_name(rid)
        parts.append((f"Anunțul dă linia {short} doar ca „{' – '.join(names)}”, fără stațiile de pe traseu.",
                      f"The notice gives line {short} only as „{' – '.join(names)}”, without the stops on the way."))
    else:
        parts += [_REASON_TEXT[x] for x in reasons if x in _REASON_TEXT]
    n_dirs = ("un sens", "one direction") if len(by_dir) == 1 else ("ambele sensuri", "both directions")
    n = len(rows)
    de = " de" if n >= 20 and (n % 100 >= 20 or n % 100 == 0) else ""
    parts.append(("1 stație" if n == 1 else f"{n}{de} stații", "1 stop" if n == 1 else f"{n} stops"))
    parts[-1] = (f"{parts[-1][0]}, {n_dirs[0]}.", f"{parts[-1][1]}, {n_dirs[1]}.")
    if cut:
        parts.append((f"{_cap(_lines(g['others'], mode, 0))} nu mai opresc în aceste stații și niciun alt "
                      f"{_MODE[mode][0]} nu oprește aici în interval: propunere „nu oprește”.",
                      f"{_cap(_lines(g['others'], mode, 1))} lose these stops and no other {_MODE[mode][1]} "
                      f"stops here in the window: suggested „does not stop”."))
    elif g["still"]:
        parts.append((f"{_cap(_lines(g['still'], mode, 0))} încă opresc în unele dintre ele.",
                      f"{_cap(_lines(g['still'], mode, 1))} still stop at some of them."))
    return DecisionGroup(
        id=gid,
        routeId=rid,
        question=question,
        reason=I18n(ro=" ".join(p[0] for p in parts), en=" ".join(p[1] for p in parts)),
        suggested="affected" if cut else None,
        rows=[StopRowKey(stopId=r["stopId"], routeId=rid, directionId=r["directionId"]) for r in rows],
    )


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
        decisionGroups=decision_groups(closure, rows),
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
    """The stored Analysis (decisions applied), or None if never analyzed.

    The decision groups are a view of the rows: computed again here, so an analysis
    stored before they existed has them too.
    """
    try:
        data = state.read("closures", closure_id, state.PART_ANALYSIS)
        closure = state.read("closures", closure_id)
    except ValueError:
        return None
    if data is None:
        return None
    if closure is not None:
        data = dict(data, decisionGroups=[g.model_dump(mode="json") for g in decision_groups(closure, data["stops"])])
    return Analysis.model_validate(data)


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
