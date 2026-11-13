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


def _service(closure: dict, rows: list[dict]) -> imp.ServiceState | None:
    """Who still serves which stop in the window (impact's rule), or None outside every timetable.
    An undecided row is pending: never named as a line that still serves the stop."""
    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    tt = imp.timetable_for(start)
    counts = imp.departure_counts(imp.count_window(start, end, tt), tt)
    if counts is None:
        return None
    return imp.ServiceState.build(counts, {imp.row_key(r) for r in rows if imp.counts_as_lost(r)},
                                  {imp.row_key(r) for r in rows if _undecided(r)})


def _no_service_stops(closure: dict, rows: list[dict], svc: imp.ServiceState | None) -> list[NoticeStop]:
    """The impact's suspended stops: no departure of any line left in the window, and not served
    according to the notice (T12)."""
    if svc is None:
        return []
    suspended, _ = imp.certain_suspended(closure, svc)
    out: dict[str, NoticeStop] = {}
    for r in rows:  # analysis order: by line, direction and stop sequence
        sid = str(r["stopId"])
        if imp.counts_as_lost(r) and sid in suspended and sid not in out:
            at_stop = [x for x in rows if str(x["stopId"]) == sid and imp.counts_as_lost(x)]
            out[sid] = NoticeStop(stopId=sid, name=r["name"], nearestServed=_nearest(al.pick_nearest(at_stop, sid), sid))
    return list(out.values())


# --- the text -------------------------------------------------------------------------------
#
# The text is shorter than `sections`: lines that lose the same stops share one block, and
# the stops both directions lose are listed once („în ambele sensuri”), then the few extra
# stops of one direction. A stop name the GTFS gives to several stops is qualified with the
# mode and the lines that serve it, when the text would otherwise give one name to a stop
# that is served and to one that is not (Catedrala Mitropolitană: tram stop vs bus stop).


def _join(items: list[str], lang: str) -> str:
    conj = texts()[lang]["and"]
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} {conj} {items[-1]}"


def _many(value: list, n: int):
    return value[0] if n == 1 else value[1]


class _Text:
    """Everything one language's text needs: rows, service state, network, qualifiers."""

    def __init__(self, closure: dict, rows: list[dict], sections: list[NoticeSection],
                 no_service: list[NoticeStop], svc: imp.ServiceState | None):
        self.closure, self.rows, self.sections, self.no_service, self.svc = closure, rows, sections, no_service, svc
        self.net = load_network()
        self.short_of = {r["id"]: r["shortName"] for r in self.net.routes}
        self.whole = _whole_lines(closure, rows)
        self.lost_rows: dict[str, list[dict]] = {}
        for r in rows:
            if imp.counts_as_lost(r):
                self.lost_rows.setdefault(str(r["stopId"]), []).append(r)
        self.headsign = {(r["routeId"], int(r["directionId"])): r.get("headsign") for r in rows if r.get("headsign")}
        self.groups = self._groups()
        self.ambiguous = self._ambiguous()

    # -- service -------------------------------------------------------------------------

    def remaining(self, sid: str) -> list[str]:
        """Route ids that still depart from a stop in the window."""
        if self.svc is None:
            return []
        return sorted({r for r, _ in self.svc.served(sid)}, key=lambda r: al._line_key(self.short_of.get(r, r)))

    def name(self, sid: str) -> str:
        rows = self.lost_rows.get(sid)
        return rows[0]["name"] if rows else (self.net.stop_by_id.get(sid) or {}).get("name") or sid

    # -- grouping ------------------------------------------------------------------------

    def _groups(self) -> list[dict]:
        """Text blocks: whole lines by mode, then lines with identical losses per direction."""
        whole_both: dict[str, list[NoticeSection]] = {}
        per_route: dict[str, dict] = {}
        order: list[tuple[str, str]] = []
        for sec in self.sections:
            did = self.whole.get(sec.routeId, "none")
            if did is None:
                if sec.mode not in whole_both:
                    order.append(("whole", sec.mode))
                whole_both.setdefault(sec.mode, []).append(sec)
                continue
            if sec.routeId not in per_route:
                per_route[sec.routeId] = {"sec": sec, "dirs": {}, "whole_dir": None}
                order.append(("route", sec.routeId))
            e = per_route[sec.routeId]
            if did != "none" and sec.directionId == did:
                e["whole_dir"] = sec
                continue
            for d in ((0, 1) if sec.directionId is None else (sec.directionId,)):
                e["dirs"][d] = sec.stopsNotServed
        blocks: list[dict] = []
        by_key: dict[tuple, dict] = {}
        for kind, key in order:
            if kind == "whole":
                blocks.append({"kind": "whole", "secs": whole_both[key]})
                continue
            e = per_route[key]
            if e["whole_dir"] is not None:
                blocks.append({"kind": "whole_dir", "secs": [e["whole_dir"]]})
            if not e["dirs"]:
                continue
            sec = e["sec"]
            a = _action_of(self.closure, sec.routeId, sec.directionId) or {}
            sig = (sec.mode, sec.action, a.get("fromStopId"), a.get("toStopId"),
                   tuple(sorted((d, tuple(s.stopId for s in stops)) for d, stops in e["dirs"].items())))
            if sig in by_key:
                by_key[sig]["secs"].append(sec)
                for d, stops in e["dirs"].items():
                    by_key[sig]["dirs"][d].append(stops)
                continue
            block = {"kind": "lines", "secs": [sec], "dirs": {d: [stops] for d, stops in e["dirs"].items()}}
            by_key[sig] = block
            blocks.append(block)
        return blocks

    def _entries(self, block: dict, d: int) -> list[dict]:
        """One entry per stop name in direction d: the stop ids and the info shown for them."""
        out: dict[str, dict] = {}
        lists = block["dirs"][d]
        for i, stop in enumerate(lists[0]):
            # the same stop as lost by every line of the block: the nearest served one of them all
            candidates = [lst[i].nearestServed for lst in lists if lst[i].nearestServed]
            own = [n for n in candidates if n.stopId == stop.stopId]
            known = [n for n in candidates if n.distanceMeters is not None]
            near = own[0] if own else (min(known, key=lambda n: n.distanceMeters) if known else None)
            e = out.setdefault(stop.name, {"name": stop.name, "ids": [], "info": None})
            e["ids"].append(stop.stopId)
            if e["info"] is None and near is not None:
                if near.stopId == stop.stopId:
                    lines = self.remaining(stop.stopId)
                    e["info"] = ("still", tuple(lines)) if lines else None
                else:
                    e["info"] = ("near", near.stopId, near.distanceMeters, near.approximate)
            if e["info"] is None and self.svc is not None and self.svc.pending.get(stop.stopId):
                e["info"] = ("pending",)  # the only line left here is undecided: never named as serving
        return list(out.values())

    def direction_label(self, block: dict, d: int) -> str:
        heads = [self.headsign.get((sec.routeId, d)) for sec in block["secs"]]
        return " / ".join(dict.fromkeys(h for h in heads if h))

    def layout(self, block: dict) -> list[tuple[str, int | None, list[tuple[dict, dict[int, dict]]]]]:
        """[(header kind, direction, [(entry, {direction: entry})])]: the merged lists of a block."""
        dirs = sorted(block["dirs"])
        per_dir = {d: self._entries(block, d) for d in dirs}
        if len(dirs) == 2:
            names = {d: [e["name"] for e in per_dir[d]] for d in dirs}
            common = [n for n in names[dirs[0]] if n in names[dirs[1]]]
            extra = {d: [e for e in per_dir[d] if e["name"] not in common] for d in dirs}
            if common and all(len(x) <= 2 for x in extra.values()):
                by_name = {d: {e["name"]: e for e in per_dir[d]} for d in dirs}
                both = [(by_name[dirs[0]][n], {d: by_name[d][n] for d in dirs}) for n in common]
                out = [("both", None, both)]
                out += [("extra", d, [(e, {d: e}) for e in extra[d]]) for d in dirs if extra[d]]
                return out
        return [("direction", d, [(e, {d: e}) for e in per_dir[d]]) for d in dirs]

    # -- same-name stops ------------------------------------------------------------------

    def _ambiguous(self) -> set[str]:
        """Names the text gives to a served stop and to a not-served one."""
        if self.svc is None:
            return set()
        mentioned: dict[str, set[str]] = {}

        def add(sid: str, name: str | None = None) -> None:
            mentioned.setdefault(name or self.name(sid), set()).add(sid)

        for block in self.groups:
            if block["kind"] != "lines":
                continue
            for _, _, items in self.layout(block):
                for _, by_dir in items:
                    for e in by_dir.values():
                        for sid in e["ids"]:
                            add(sid, e["name"])
                        if e["info"] and e["info"][0] == "near":
                            add(e["info"][1])
        same_name: dict[str, list[str]] = {}
        for s in self.net.stops:
            same_name.setdefault(s["name"], []).append(str(s["id"]))
        for s in self.no_service:  # „no service at X” must not be read as the X across the street
            add(s.stopId, s.name)
            for sid in same_name.get(s.name, []):
                add(sid, s.name)
        return {name for name, ids in mentioned.items()
                if len({bool(self.remaining(sid)) for sid in ids}) > 1}

    def _mode_of_lost(self, sid: str) -> str:
        rows = self.lost_rows.get(sid) or []
        return route_mode(rows[0]["routeId"]) if rows else "bus"

    def served_label(self, sid: str, lang: str) -> str:
        name = self.name(sid)
        lines = self.remaining(sid)
        if name not in self.ambiguous or not lines:
            return name
        t = texts()[lang]
        modes = {route_mode(r) for r in lines}
        shorts = _join([self.short_of.get(r, r) for r in lines], lang)
        prefix = _many(t["stop_of"][modes.pop()], len(lines)) if len(modes) == 1 else _many(t["stop_of_mixed"], len(lines))
        return f"{name} ({prefix} {shorts})"

    def lost_label(self, name: str, mode: str, lang: str) -> str:
        return f"{name} ({texts()[lang]['stop_of_mode'][mode]})" if name in self.ambiguous else name

    def no_service_label(self, sid: str, lang: str) -> str:
        name = self.name(sid)
        if name not in self.ambiguous:
            return name
        t = texts()[lang]
        mode = self._mode_of_lost(sid)
        q = t["stop_of_mode"][mode]
        # another stop of this name and mode is still served: say which side of the street this one is
        others = [s["id"] for s in self.net.stops if s["name"] == name and s["id"] != sid and self.remaining(s["id"])]
        if any(route_mode(r) == mode for o in others for r in (self.net.stop_by_id[o].get("routeIds") or [])):
            rows = self.lost_rows.get(sid) or []
            head = next((r.get("headsign") for r in rows if r["routeId"] not in self.whole and r.get("headsign")),
                        next((r.get("headsign") for r in rows if r.get("headsign")), None))
            if head and head != name:
                q += " " + t["towards"].format(headsign=head)
        return f"{name} ({q})"

    # -- rendering -----------------------------------------------------------------------

    def vehicles(self, route_ids: tuple[str, ...], lang: str) -> str:
        t = texts()[lang]
        modes = {route_mode(r) for r in route_ids}
        names = _join([self.short_of.get(r, r) for r in route_ids], lang)
        word = _many(t["vehicle"][modes.pop()], len(route_ids)) if len(modes) == 1 else _many(t["mixed_lines"], len(route_ids))
        return f"{word} {names}"

    def info(self, entries: list[tuple[int, dict]], lang: str, block: dict) -> str | None:
        """What a citizen does instead, for one stop name in one or both directions."""
        t = texts()[lang]
        infos = [(d, e["info"]) for d, e in entries if e["info"]]
        if not infos:
            return None

        def distance(meters: list[int], approx: bool) -> str:
            m = "–".join(str(x) for x in sorted(set(meters)))
            return t["distance_approx" if approx else "distance"].format(meters=m)

        def one(info: tuple) -> str:
            if info[0] == "pending":
                return t["pending"]
            if info[0] == "still":
                return t["still"].format(lines=self.vehicles(info[1], lang))
            return t["near"].format(name=self.served_label(info[1], lang),
                                    distance=distance([al._round10(info[2])], info[3]))

        complete = len(infos) == len(entries)
        if complete and all(i[0] == "pending" for _, i in infos):
            return one(infos[0][1])
        if complete and all(i[0] == "still" for _, i in infos) and len({i[1] for _, i in infos}) == 1:
            return one(infos[0][1])
        if complete and all(i[0] == "near" for _, i in infos):
            labels = [self.served_label(i[1], lang) for _, i in infos]
            if len(set(labels)) == 1:  # the same stop name on both sides: one name, the two distances
                return t["near"].format(name=labels[0], distance=distance(
                    [al._round10(i[2]) for _, i in infos], any(i[3] for _, i in infos)))
            parts = [t["near_part"].format(headsign=self.direction_label(block, d), name=label,
                                           distance=distance([al._round10(i[2])], i[3]))
                     for (d, i), label in zip(infos, labels)]
            return t["near_split"].format(parts="; ".join(parts))
        if len(infos) == 1 and complete:
            return one(infos[0][1])
        parts = [t["split_part"].format(headsign=self.direction_label(block, d), info=one(i)) for d, i in infos]
        return "; ".join(parts)

    def block_text(self, block: dict, lang: str) -> str:
        t = texts()[lang]
        secs = block["secs"]
        mode = secs[0].mode
        n = len(secs)
        shorts = [s.shortName for s in secs]
        label = (t["line"].format(line=shorts[0], mode=t["modes"][mode]) if n == 1
                 else t["lines"].format(lines=_join(shorts, lang), mode=t["modes"][mode]))
        if block["kind"] == "whole":
            return _many(t["whole_line"], n).format(line=label)
        if block["kind"] == "whole_dir":
            return t["whole_line_direction"].format(line=label, headsign=secs[0].headsign or "")
        lines = [self.action_sentence(secs[0], label, n, lang)]
        verb = _many(t["verb"], n)
        for kind, d, items in self.layout(block):
            if kind == "both":
                lines.append(t["both_directions"].format(verb=verb))
            else:
                key = "direction_extra" if kind == "extra" else "direction"
                lines.append(t[key].format(headsign=self.direction_label(block, d), verb=verb))
            for entry, by_dir in items:
                stop = self.lost_label(entry["name"], mode, lang)
                info = self.info(sorted(by_dir.items()), lang, block)
                lines.append(t["stop_info"].format(stop=stop, info=al._cap(info)) if info else t["stop"].format(stop=stop))
        for sec in secs:  # T12: the route the notice gives a shortened line, as STPT wrote it (no GTFS timetable)
            a = _action_of(self.closure, sec.routeId, sec.directionId) or {}
            if a.get("action") == "shortened" and a.get("stopNames"):
                lines.append(t["announced_route"].format(line=sec.shortName, route=" – ".join(a["stopNames"])))
        return "\n".join(lines)

    def action_sentence(self, sec: NoticeSection, label: str, n: int, lang: str) -> str:
        t = texts()[lang]
        if sec.action == "suspended":
            a = _action_of(self.closure, sec.routeId, sec.directionId) or {}
            names = [(self.net.stop_by_id.get(a.get(k) or "") or {}).get("name") for k in ("fromStopId", "toStopId")]
            if all(names):
                return _many(t["action_suspended_section"], n).format(line=label, from_stop=names[0], to_stop=names[1])
            return _many(t["action_suspended"], n).format(line=label)
        if sec.action in ("shortened", "rerouted"):
            return _many(t[f"action_{sec.action}"], n).format(line=label)
        return _many(t["action_none"], n).format(line=label)


def _text(ctx: _Text, unsure_count: int, map_url: str, lang: str) -> str:
    t = texts()[lang]
    closure, rows, net = ctx.closure, ctx.rows, ctx.net
    blocks: list[str] = []
    if unsure_count:
        blocks.append(t["draft"].format(count=_count_stops(unsure_count, lang)))

    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    window = al._cap(window_words(start, end, lang, al.is_open_end(closure)))
    title = closure.get("title") or {}
    reason = (title.get(lang) or (title.get("ro") if lang == "en" else None) or "").strip().rstrip(".")
    blocks.append(t["intro"].format(window=window, reason=reason) if reason else window + ".")

    blocks.extend(ctx.block_text(b, lang) for b in ctx.groups)

    if ctx.no_service:  # two stops of one name (one per side of the street) are named once
        names = list(dict.fromkeys(ctx.no_service_label(s.stopId, lang) for s in ctx.no_service))
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
    svc = _service(c, rows)
    no_service = _no_service_stops(c, rows, svc)
    map_url = al.alert_url(c["id"], None, base_url)
    ctx = _Text(c, rows, sections, no_service, svc)
    text = I18n(**{lang: _text(ctx, unsure_count, map_url, lang) for lang in LANGS})

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
