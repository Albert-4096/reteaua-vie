"""The public notice generated from a closure (D-013, GET /api/closures/{id}/notice).

Today's notices make people guess which stops they mean. This one names every
stop a line does not serve, per direction, each with the nearest served stop
and the walking distance, the stops with no service at all, the temporary line
and the map link. Deterministic templates (templates/notice_text.json), no LLM.

    build_notice(closure, analysis, impact) -> GeneratedNotice    pure

Every name, time and distance comes from the closure, the analysis (with its
decisions), the impact, the network and the GTFS; a clause with no data is
left out. While unsure rows have no decision the notice is a draft: the RO
text starts with „Ciornă: …” and the unsure stops are listed apart, never in
the final lists.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.common.city import load_network, route_mode
from app.common.timeutil import parse_iso
from app.config import TZ
from app.m1_disruption import alerts as al
from app.m1_disruption import impact as imp
from app.models.base import I18n, Model, Provenance, Window
from app.models.v1 import Analysis, Closure, Impact, TemporaryRoute

TEMPLATES = Path(__file__).resolve().parent / "templates"
LANGS = ("ro", "en")


@lru_cache(maxsize=1)
def texts() -> dict:
    return json.loads((TEMPLATES / "notice_text.json").read_text(encoding="utf-8"))


# --- the contract type (CONTRACT v2.4, GeneratedNotice) --------------------------------------


class NoticeNearest(Model):
    stopId: str
    name: str
    distanceMeters: float | None
    approximate: bool                  # True: straight line × 1.3, not a walking path


class NoticeStop(Model):
    stopId: str
    name: str
    nearestServed: NoticeNearest | None = None


class NoticeSection(Model):
    routeId: str
    shortName: str
    mode: Literal["bus", "tram", "trolleybus"]
    directionId: Literal[0, 1] | None  # null = both directions (whole line, or the same stops both ways)
    headsign: str | None
    action: Literal["suspended", "shortened", "rerouted"] | None   # null = no routeAction (drawn closure)
    stopsNotServed: list[NoticeStop]


class GeneratedNotice(Model):
    closureId: str
    status: Literal["draft", "final"]
    unsureCount: int
    window: Window
    text: I18n
    sections: list[NoticeSection]
    stopsWithNoService: list[NoticeStop]
    temporaryRoutes: list[TemporaryRoute]
    sourceText: str | None
    sourceUrl: str | None
    mapUrl: str
    provenance: list[Provenance]


# --- window in words ------------------------------------------------------------------------


def _date(d: datetime, lang: str) -> str:
    t = texts()[lang]
    months = al.RO_MONTHS if lang == "ro" else al.EN_MONTHS
    return t["date"].format(weekday=t["days"][d.weekday()], day=d.day, month=months[d.month - 1], year=d.year)


def window_words(start: datetime, end: datetime, lang: str, open_end: bool = False) -> str:
    """'duminică, 8 noiembrie 2026, între orele 10:00 și 18:00' (Europe/Bucharest, no system locale)."""
    t = texts()[lang]
    s = start.astimezone(TZ)
    stime = f"{s.hour:02d}:{s.minute:02d}"
    if open_end:
        at = t["window_open_start"].format(start=stime) if (s.hour, s.minute) != (0, 0) else ""
        return t["window_open"].format(day=_date(s, lang), start=at)
    eday, eh, em = al._end_parts(end.astimezone(TZ))
    etime = f"{eh:02d}:{em:02d}"
    if eday.date() == s.date():
        return t["window_same_day"].format(day=_date(s, lang), start=stime, end=etime)
    return t["window_days"].format(day=_date(s, lang), start=stime, end_day=_date(eday, lang), end=etime)


def _count_stops(n: int, lang: str) -> str:
    one, many = texts()[lang]["stop_unit"]
    if n == 1:
        return f"1 {one}"
    if lang == "ro" and al._ro_needs_de(n):
        return f"{n} de {many}"
    return f"{n} {many}"


# --- rows -----------------------------------------------------------------------------------


def _undecided(row: dict) -> bool:
    return row["state"] == "unsure" and row.get("confirmed") is None


def _nearest(row_nearest: dict | None, stop_id: str) -> NoticeNearest | None:
    if not row_nearest:
        return None
    dist = row_nearest.get("distanceMeters")
    approximate = False
    if dist is not None and str(row_nearest["stopId"]) != str(stop_id):
        # the same walking query impact used: exact=False means straight line × 1.3
        _, exact = imp.walk_distance(str(stop_id), str(row_nearest["stopId"]))
        approximate = not exact
    return NoticeNearest(stopId=str(row_nearest["stopId"]), name=row_nearest["name"],
                         distanceMeters=dist, approximate=approximate)


def _stop(rows: list[dict]) -> NoticeStop:
    """One stop from its rows (one row per direction when both directions merge)."""
    first = rows[0]
    near = al.pick_nearest(rows, first["stopId"])
    return NoticeStop(stopId=str(first["stopId"]), name=first["name"], nearestServed=_nearest(near, first["stopId"]))


def _action_of(closure: dict, route_id: str, direction_id: int | None) -> dict | None:
    actions = [a for a in closure.get("routeActions") or [] if a["routeId"] == route_id]
    for a in actions:
        if a.get("directionId") == direction_id:
            return a
    for a in actions:
        if a.get("directionId") is None:
            return a
    return None


def _route_order(closure: dict, analysis: dict) -> list[str]:
    """Lines in the order the notice names them, then the rest in the analysis order."""
    seen: dict[str, None] = {}
    for a in closure.get("routeActions") or []:
        seen.setdefault(a["routeId"], None)
    for r in analysis.get("routes") or []:
        seen.setdefault(r["routeId"], None)
    for r in analysis.get("stops") or []:
        seen.setdefault(r["routeId"], None)
    return list(seen)


def _whole_lines(closure: dict, rows: list[dict]) -> dict[str, int | None]:
    """Lines the closure suspends as a whole (routeId -> direction, None = both) and whose
    rows are all lost: the text then says „Linia 4 nu circulă” with no stop list."""
    out = {}
    for a in al._whole_line_actions(closure):
        rid, did = a["routeId"], a.get("directionId")
        route_rows = [r for r in rows if r["routeId"] == rid and (did is None or int(r["directionId"]) == did)]
        if route_rows and all(imp.counts_as_lost(r) for r in route_rows):
            out[rid] = None if did is None else int(did)
    return out


def _sections(closure: dict, rows: list[dict]) -> list[NoticeSection]:
    net = load_network()
    whole = _whole_lines(closure, rows)
    out: list[NoticeSection] = []
    for rid in _route_order(closure, {"stops": rows}):
        route_rows = [r for r in rows if r["routeId"] == rid]
        lost = [r for r in route_rows if imp.counts_as_lost(r)]
        if not lost:
            continue
        route = net.route_by_id.get(rid) or {}
        short = route.get("shortName") or lost[0].get("routeShortName") or rid
        mode = route_mode(rid, route.get("type"))
        by_dir: dict[int, list[dict]] = {}
        for r in lost:
            by_dir.setdefault(int(r["directionId"]), []).append(r)

        def section(direction_id: int | None, stop_rows: list[list[dict]], action: dict | None) -> NoticeSection:
            headsign = None
            if direction_id is not None:
                headsign = next((r.get("headsign") for r in by_dir[direction_id] if r.get("headsign")), None)
            return NoticeSection(routeId=rid, shortName=short, mode=mode, directionId=direction_id,
                                 headsign=headsign, action=action.get("action") if action else None,
                                 stopsNotServed=[_stop(g) for g in stop_rows])

        if rid in whole:  # the JSON still lists every stop (map, poster); the text needs no list
            did = whole[rid]
            groups: dict[str, list[dict]] = {}
            for d in (sorted(by_dir) if did is None else [did]):
                for r in by_dir[d]:
                    groups.setdefault(str(r["stopId"]), []).append(r)
            out.append(section(did, list(groups.values()), _action_of(closure, rid, did)))
            others = [d for d in sorted(by_dir) if did is not None and d != did]
            for d in others:
                out.append(section(d, [[r] for r in by_dir[d]], _action_of(closure, rid, d)))
            continue

        ids = {d: [str(r["stopId"]) for r in rs] for d, rs in by_dir.items()}
        if set(by_dir) == {0, 1} and set(ids[0]) == set(ids[1]):
            other = {str(r["stopId"]): r for r in by_dir[1]}
            merged = [[r, other[str(r["stopId"])]] for r in by_dir[0]]
            action = _action_of(closure, rid, 0) or _action_of(closure, rid, 1)
            out.append(section(None, merged, action))
            continue
        for d in sorted(by_dir):
            out.append(section(d, [[r] for r in by_dir[d]], _action_of(closure, rid, d)))
    return out


def _no_service_stops(closure: dict, rows: list[dict]) -> list[NoticeStop]:
    """The impact's suspended stops: no departure of any line left in the window."""
    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    tt = imp.timetable_for(start)
    counts = imp.departure_counts(imp.count_window(start, end, tt), tt)
    if counts is None:
        return []
    lost_rows = [r for r in rows if imp.counts_as_lost(r)]
    svc = imp.ServiceState.build(counts, {imp.row_key(r) for r in lost_rows})
    suspended = svc.suspended_stops()
    out: dict[str, NoticeStop] = {}
    for r in lost_rows:  # analysis order: by line, direction and stop sequence
        sid = str(r["stopId"])
        if sid in suspended and sid not in out:
            out[sid] = NoticeStop(stopId=sid, name=r["name"])
    return list(out.values())


# --- the text -------------------------------------------------------------------------------


def _line_label(sec: NoticeSection, lang: str) -> str:
    t = texts()[lang]
    return t["line"].format(line=sec.shortName, mode=t["modes"][sec.mode])


def _action_sentence(sec: NoticeSection, closure: dict, lang: str) -> str:
    t = texts()[lang]
    line = _line_label(sec, lang)
    if sec.action == "suspended":
        a = _action_of(closure, sec.routeId, sec.directionId) or {}
        net = load_network()
        names = [(net.stop_by_id.get(a.get(k) or "") or {}).get("name") for k in ("fromStopId", "toStopId")]
        if all(names):
            return t["action_suspended_section"].format(line=line, from_stop=names[0], to_stop=names[1])
        return t["action_suspended"].format(line=line)
    if sec.action in ("shortened", "rerouted"):
        return t[f"action_{sec.action}"].format(line=line)
    return t["action_none"].format(line=line)


def _stop_line(stop: NoticeStop, short_of: dict[str, str], nearest_lines: dict[str, list[str]], lang: str) -> str:
    t = texts()[lang]
    n = stop.nearestServed
    if n is None or n.distanceMeters is None:
        return t["stop"].format(stop=stop.name)
    if n.stopId == stop.stopId:
        shorts = [short_of.get(r, r) for r in nearest_lines.get(stop.stopId) or []]
        if not shorts:
            return t["stop"].format(stop=stop.name)
        return t["stop_still_served"].format(stop=stop.name, lines=al.lines_phrase(shorts, lang))
    meters = al._round10(n.distanceMeters)
    distance = t["distance_approx" if n.approximate else "distance"].format(meters=meters)
    name = n.name + (t["same_name"] if n.name == stop.name else "")
    return t["stop_nearest"].format(stop=stop.name, name=name, distance=distance)


def _text(closure: dict, rows: list[dict], sections: list[NoticeSection], no_service: list[NoticeStop],
          unsure_count: int, map_url: str, lang: str) -> str:
    t = texts()[lang]
    net = load_network()
    short_of = {r["id"]: r["shortName"] for r in net.routes}
    whole = _whole_lines(closure, rows)
    # the lines that still serve a stop (the row's nearestServed is the stop itself)
    nearest_lines: dict[str, list[str]] = {}
    for r in rows:
        n = r.get("nearestServed")
        if n and str(n["stopId"]) == str(r["stopId"]) and imp.counts_as_lost(r):
            nearest_lines.setdefault(str(r["stopId"]), n.get("routeIds") or [])

    blocks: list[str] = []
    if unsure_count:
        blocks.append(t["draft"].format(count=_count_stops(unsure_count, lang)))

    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    window = al._cap(window_words(start, end, lang, al.is_open_end(closure)))
    title = closure.get("title") or {}
    reason = (title.get(lang) or (title.get("ro") if lang == "en" else None) or "").strip().rstrip(".")
    blocks.append(t["intro"].format(window=window, reason=reason) if reason else window + ".")

    by_route: dict[str, list[NoticeSection]] = {}
    for sec in sections:
        by_route.setdefault(sec.routeId, []).append(sec)
    for rid, secs in by_route.items():
        first = secs[0]
        line = _line_label(first, lang)
        rest = secs
        if rid in whole:
            if whole[rid] is None:
                blocks.append(t["whole_line"].format(line=line))
                continue
            blocks.append(t["whole_line_direction"].format(line=line, headsign=first.headsign or ""))
            rest = secs[1:]
            if not rest:
                continue
        lines = [_action_sentence(rest[0], closure, lang)]
        for sec in rest:
            head = t["both_directions"] if sec.directionId is None else \
                t["direction"].format(headsign=sec.headsign or "")
            lines.append(head)
            lines.extend(_stop_line(s, short_of, nearest_lines, lang) for s in sec.stopsNotServed)
        blocks.append("\n".join(lines))

    if no_service:  # two stops of one name (one per side of the street) are named once
        names = list(dict.fromkeys(s.name for s in no_service))
        blocks.append(t["no_service"].format(stops=", ".join(names)))

    temporary = al._Ctx(closure).temporary[lang].strip()
    if temporary:
        blocks.append(temporary)

    if unsure_count:
        groups: dict[tuple[str, int], list[dict]] = {}
        for r in rows:
            if _undecided(r):
                groups.setdefault((r["routeId"], int(r["directionId"])), []).append(r)
        lines = [t["to_confirm"]]
        for (rid, _d), rs in groups.items():
            route = net.route_by_id.get(rid) or {}
            label = t["line"].format(line=route.get("shortName") or rs[0]["routeShortName"],
                                     mode=t["modes"][route_mode(rid, route.get("type"))])
            headsign = next((r.get("headsign") for r in rs if r.get("headsign")), None)
            names = ", ".join(r["name"] for r in rs)
            if headsign:
                lines.append(t["to_confirm_line"].format(line=label, headsign=headsign, stops=names))
            else:
                lines.append(f"– {label}: {names}.")
        blocks.append("\n".join(lines))

    blocks.append(t["map"].format(url=map_url))
    return _DOUBLE_STOP.sub(".", "\n\n".join(blocks))  # „Canton C.F.R..” -> „Canton C.F.R.”


_DOUBLE_STOP = re.compile(r"(?<=\w)\.\.(?!\.)")


# --- the notice -----------------------------------------------------------------------------


def _as_dict(obj) -> dict:
    return obj.model_dump(mode="json", by_alias=True) if hasattr(obj, "model_dump") else dict(obj)


def build_notice(closure: Closure | dict, analysis: Analysis | dict, impact: Impact | dict,
                 base_url: str | None = None) -> GeneratedNotice:
    """The public notice of one closure. Pure: reads only its inputs, the network and the GTFS."""
    c, a, i = _as_dict(closure), _as_dict(analysis), _as_dict(impact)
    rows = a.get("stops") or []
    unsure_count = sum(1 for r in rows if _undecided(r))
    sections = _sections(c, rows)
    no_service = _no_service_stops(c, rows)
    map_url = al.alert_url(c["id"], None, base_url)
    text = I18n(**{lang: _text(c, rows, sections, no_service, unsure_count, map_url, lang) for lang in LANGS})

    provenance: list[Provenance] = []
    seen = set()
    for p in [*(a.get("provenance") or []), *(i.get("provenance") or [])]:
        key = (p["source"], p.get("version"), p.get("note"))
        if key not in seen:
            seen.add(key)
            provenance.append(Provenance(**p))

    return GeneratedNotice(
        closureId=c["id"],
        status="draft" if unsure_count else "final",
        unsureCount=unsure_count,
        window=Window(**c["window"]),
        text=text,
        sections=sections,
        stopsWithNoService=no_service,
        temporaryRoutes=[TemporaryRoute(**tr) for tr in c.get("temporaryRoutes") or []],
        sourceText=c.get("sourceText"),
        sourceUrl=c.get("sourceUrl"),
        mapUrl=map_url,
        provenance=provenance,
    )
