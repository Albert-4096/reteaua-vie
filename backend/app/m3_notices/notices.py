"""M3 neighbourhood notices (SPEC §6.3): one ZoneNotice per neighbourhood hit.

A zone (`/api/zones`) is hit when a stop the closure suspends lies in it, or
when the closure buffer intersects it. Per zone:
- streets: named OSM ways inside the buffer and the zone, matched to the city's
  street register (nomenclator); codGis is null when the register has no match
  (never invented). Cross streets that only touch the buffer are left out.
- title / body: the SPEC §6.3 template in RO and EN, with the real window,
  street names, lines, stops and the nearest served stop from the analysis
  (walking distance from M1's impact, rounded to 10 m).
- alertIds: the GTFS-RT alerts of the same closure that concern this zone,
  once the closure is published; publishedAt is null until then.

Public:
    notices_for(closure_id) -> list[ZoneNotice]   any analyzed closure
    feed(at=None) -> list[ZoneNotice]              published closures whose window has not ended
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from app import config
from app.common import state
from app.common.city import load_network, load_zones, zone_for_point
from app.common.errors import not_found
from app.common.geo import buffer_m, from_geojson, to_metric
from app.common.timeutil import parse_iso
from app.config import TZ
from app.m1_disruption.alerts import EN_MONTHS, RO_MONTHS, is_open_end, lines_phrase, pick_nearest
from app.m1_disruption.impact import counts_as_lost
from app.m3_notices import osm_ways
from app.models.base import I18n, Window
from app.models.v2 import NoticeStreet, ZoneNotice

RO_DAYS = ["luni", "marți", "miercuri", "joi", "vineri", "sâmbătă", "duminică"]
EN_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MIN_EXTRA_METERS = 20.0   # a street counts when more of it lies in the buffer than a crossing would

ACTION_RANK = {"suspended": 0, "shortened": 1, "rerouted": 2}
ACTION_TEXT = {
    "ro": {"suspended": ("nu circulă", "nu circulă"),
           "shortened": ("circulă pe traseu scurtat", "circulă pe traseu scurtat"),
           "rerouted": ("ocolește zona lucrărilor", "ocolesc zona lucrărilor")},
    "en": {"suspended": ("does not run", "do not run"),
           "shortened": ("runs on a shortened route", "run on a shortened route"),
           "rerouted": ("is diverted around the works", "are diverted around the works")},
}


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _round10(meters: float) -> int:
    return int(round(float(meters) / 10.0) * 10)


# --- window -------------------------------------------------------------------------------


def _day(d: datetime, lang: str) -> str:
    if lang == "ro":
        return f"{RO_DAYS[d.weekday()]} {d.day} {RO_MONTHS[d.month - 1]} {d.year}"
    return f"{EN_DAYS[d.weekday()]} {d.day} {EN_MONTHS[d.month - 1]} {d.year}"


def window_phrase(start: datetime, end: datetime, lang: str, open_end: bool = False) -> str:
    """'duminică 8 noiembrie 2026, 10:00–18:00'; an end at 00:00 reads as 24:00 of the day before."""
    s, e = start.astimezone(TZ), end.astimezone(TZ)
    stime = f"{s.hour:02d}:{s.minute:02d}"
    if open_end:
        if lang == "ro":
            return f"din {_day(s, lang)}, {stime}, până la finalizarea lucrărilor"
        return f"from {_day(s, lang)}, {stime}, until the works end"
    if e.hour == 0 and e.minute == 0:
        eday, etime = e - timedelta(days=1), "24:00"
    else:
        eday, etime = e, f"{e.hour:02d}:{e.minute:02d}"
    if eday.date() == s.date():
        return f"{_day(s, lang)}, {stime}–{etime}"
    return f"{_day(s, lang)}, {stime} – {_day(eday, lang)}, {etime}"


# --- streets in the buffer -------------------------------------------------------------------


def _register_match(osm_name: str) -> tuple[str, str | None]:
    """(name, codGis): the register's full name and code, or the OSM name and None."""
    from app.m1_disruption.parser import norm, register, resolve_street

    _streets, cur, old = register()
    key = norm(osm_name)
    st = cur.get(key) or old.get(key) or resolve_street(osm_name)
    if st is None:
        return osm_name, None
    return st.name, st.cod_gis


def streets_in(buffer: BaseGeometry, buffer_meters: float, area: BaseGeometry | None = None,
               closure_meters: float | None = None) -> list[NoticeStreet]:
    """Register-matched names of the OSM streets that run inside the buffer (∩ area), longest first.

    `closure_meters`: length of the closure line. The street it lies on has about that length plus
    2 × buffer inside the buffer, so for a short closure the margin over a crossing is at most half of it.
    """
    w = osm_ways.named_ways()
    region = buffer if area is None else buffer.intersection(area)
    if region.is_empty:
        return []
    region_m = to_metric(region)
    buffer_m_ = to_metric(buffer)
    extra = MIN_EXTRA_METERS if closure_meters is None else min(MIN_EXTRA_METERS, closure_meters / 2)
    crossing = 2 * float(buffer_meters) + extra
    lengths: dict[tuple[str, str | None], float] = {}
    for i in osm_ways.ways_in(region):
        # a street that only crosses the closure has about 2 × buffer of its length inside it
        if w.lines_m[i].intersection(buffer_m_).length <= crossing:
            continue
        inside = w.lines_m[i].intersection(region_m).length
        if inside <= 0:
            continue
        key = _register_match(w.names[i])
        lengths[key] = lengths.get(key, 0.0) + inside
    ranked = sorted(lengths.items(), key=lambda kv: (-kv[1], kv[0][0]))
    return [NoticeStreet(name=name, codGis=cod) for (name, cod), _ in ranked]


# --- inputs -----------------------------------------------------------------------------------


def _load(closure_id: str) -> tuple[dict, dict]:
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id}.")
    from app.m1_disruption.analysis import get_analysis

    analysis = get_analysis(closure_id)
    if analysis is None:
        raise not_found(f"Closure {closure_id} was never analyzed.", code="NOT_ANALYZED")
    return closure, analysis.model_dump(mode="json")


def _published(closure_id: str) -> dict | None:
    try:
        return state.read("published", closure_id)
    except ValueError:
        return None


def _route_actions(closure: dict) -> dict[str, str]:
    """routeId -> the strongest action the closure gives it (suspended > shortened > rerouted)."""
    out: dict[str, str] = {}
    for a in closure.get("routeActions") or []:
        cur = out.get(a["routeId"])
        if cur is None or ACTION_RANK[a["action"]] < ACTION_RANK[cur]:
            out[a["routeId"]] = a["action"]
    return out


# --- text ---------------------------------------------------------------------------------------


def _lines_sentences(route_ids: list[str], actions: dict[str, str], lang: str) -> list[str]:
    short_of = {r["id"]: r["shortName"] for r in load_network().routes}
    groups: dict[str, list[str]] = {}
    for rid in route_ids:
        groups.setdefault(actions.get(rid, "rerouted"), []).append(short_of.get(rid, rid))
    out = []
    for action in sorted(groups, key=ACTION_RANK.get):
        shorts = groups[action]
        verb = ACTION_TEXT[lang][action][0 if len(set(shorts)) == 1 else 1]
        out.append(f"{_cap(lines_phrase(shorts, lang))} {verb}.")
    return out


def _stop_sentences(stops: list[tuple[str, list[dict]]], lang: str) -> list[str]:
    """One sentence per stop name: not served + nearest served stop, or which lines skip it."""
    short_of = {r["id"]: r["shortName"] for r in load_network().routes}
    out = []
    for name, rows in stops:
        ids = list(dict.fromkeys(str(r["stopId"]) for r in rows))
        nearest = [pick_nearest([r for r in rows if str(r["stopId"]) == s], s) for s in ids]
        still = [n for s, n in zip(ids, nearest) if n and str(n.get("stopId")) == s]
        lost_lines = [r.get("routeShortName") or short_of.get(r["routeId"], r["routeId"]) for r in rows]
        if still:
            keep = sorted({r for n in still for r in n.get("routeIds") or []})
            keep_shorts = [short_of.get(r, r) for r in keep]
            if lang == "ro":
                verb = "nu oprește" if len(set(lost_lines)) == 1 else "nu opresc"
                text = f"În stația {name} {verb} {lines_phrase(lost_lines, lang)}"
                text += f"; stația rămâne deservită de {lines_phrase(keep_shorts, lang)}." if keep_shorts else "."
            else:
                text = f"At the {name} stop, {lines_phrase(lost_lines, lang)} will not stop"
                text += f"; the stop is still served by {lines_phrase(keep_shorts, lang)}." if keep_shorts else "."
            out.append(text)
            continue
        known = [n for n in nearest if n and n.get("distanceMeters") is not None]
        best = min(known, key=lambda n: float(n["distanceMeters"])) if known else next((n for n in nearest if n), None)
        if lang == "ro":
            text = f"Stația {name} nu este deservită."
            if best is None:
                text += " Cea mai apropiată stație deservită: necunoscută."
            elif best.get("distanceMeters") is None:
                text += f" Cea mai apropiată stație: {best['name']} (distanță necunoscută)."
            else:
                text += f" Cea mai apropiată stație: {best['name']} ({_round10(best['distanceMeters'])} m)."
        else:
            text = f"The {name} stop is not served."
            if best is None:
                text += " Nearest served stop: unknown."
            elif best.get("distanceMeters") is None:
                text += f" Nearest stop: {best['name']} (distance unknown)."
            else:
                text += f" Nearest stop: {best['name']} ({_round10(best['distanceMeters'])} m)."
        out.append(text)
    return out


def _street_phrase(streets: list[NoticeStreet], lang: str, limit: int = 3) -> str:
    names = [s.name for s in streets[:limit]]
    if not names:
        return "zona marcată pe hartă" if lang == "ro" else "the area shown on the map"
    if len(names) == 1:
        return names[0]
    conj = "și" if lang == "ro" else "and"
    return f"{', '.join(names[:-1])} {conj} {names[-1]}"


# --- notices -------------------------------------------------------------------------------------


def _signature(closure: dict, analysis: dict, published: dict | None) -> str:
    blob = json.dumps([closure, analysis["stops"], (published or {}).get("publishedAt"),
                       [a.get("id") for a in (published or {}).get("alerts") or []]], sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


_memo: dict[str, tuple[str, list[ZoneNotice]]] = {}


def _share_rows(closure: dict) -> list:
    """R17: the bike-share alternatives that have a full line (stations at both ends and a route)."""
    try:
        from app.m5_bike.bike import bike_impact_for

        return [r for r in bike_impact_for(closure).shareAlternative if r.line is not None]
    except Exception:  # noqa: BLE001 - an optional line must never stop the notice
        import logging

        logging.getLogger(__name__).warning("bike-share line skipped for %s", closure.get("id"), exc_info=True)
        return []


def build_notices(closure: dict, analysis: dict, published: dict | None) -> list[ZoneNotice]:
    zones = load_zones()
    net = load_network()
    cid = closure["id"]
    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    open_end = is_open_end(closure)
    buffer_meters = float(closure.get("bufferMeters") or 30)
    buffer = buffer_m(from_geojson(closure["geometry"]), buffer_meters) if closure.get("geometry") else None
    actions = _route_actions(closure)

    lost = [r for r in analysis.get("stops") or [] if counts_as_lost(r)]
    rows_by_zone: dict[str, list[dict]] = {}
    for r in lost:
        slug = r.get("zoneSlug") or zone_for_point(*r["location"])
        if slug in zones.names:
            rows_by_zone.setdefault(slug, []).append(r)
    hit = set(rows_by_zone)
    if buffer is not None:
        hit |= {zones.slugs[int(i)] for i in zones.tree.query(buffer, predicate="intersects")}

    line_m = to_metric(from_geojson(closure["geometry"])).length if buffer is not None else None
    all_streets = streets_in(buffer, buffer_meters, closure_meters=line_m) if buffer is not None else []
    share_rows = _share_rows(closure) if buffer is not None else []
    what = {lang: window_phrase(start, end, lang, open_end) for lang in ("ro", "en")}
    title = closure.get("title") or {}
    alerts = (published or {}).get("alerts") or []
    out = []
    for slug in hit:
        shape_ = zones.shapes[zones.slugs.index(slug)]
        rows = rows_by_zone.get(slug, [])
        streets = streets_in(buffer, buffer_meters, shape_, line_m) if buffer is not None else []
        route_ids = sorted({r["routeId"] for r in rows},
                           key=lambda rid: (net.route_by_id.get(rid, {}).get("shortName", rid).zfill(4), rid))
        by_name: dict[str, list[dict]] = {}
        for r in rows:
            by_name.setdefault(r.get("name") or str(r["stopId"]), []).append(r)
        stop_ids = list(dict.fromkeys(str(r["stopId"]) for r in rows))
        body = {}
        paid_line = None
        if buffer is not None:
            from app.m6_parking import paid  # lazy: m6 reads the M3 street helpers

            paid_line = paid.notice_sentence(closure, analysis, shape_)
        for lang in ("ro", "en"):
            works = "lucrări pe" if lang == "ro" else "works on"
            parts = [f"{_cap(what[lang])}: {works} {_street_phrase(streets or all_streets, lang)}."]
            parts += _lines_sentences(route_ids, actions, lang)
            parts += _stop_sentences(list(by_name.items()), lang)
            if paid_line:
                parts.append(paid_line[0 if lang == "ro" else 1])
            share = next((r for r in share_rows if r.fromStopId in stop_ids or r.toStopId in stop_ids), None)
            if share is not None:
                parts.append(getattr(share.line, lang) or share.line.ro)
            body[lang] = " ".join(parts)
        zone_name = zones.names[slug]
        zone_stops, zone_routes = set(stop_ids), set(route_ids)
        alert_ids = []
        for a in alerts:
            ents = a.get("informedEntity") or []
            if any((e.get("stopId") in zone_stops) or (e.get("stopId") is None and e.get("routeId") in zone_routes)
                   for e in ents):
                alert_ids.append(a["id"])
        out.append(ZoneNotice(
            id=f"zn_{cid.removeprefix('cl_')}_{slug}",
            closureId=cid,
            zoneSlug=slug,
            zoneName=zone_name,
            streets=streets,
            window=Window(**closure["window"]),
            title=I18n(ro=f"{zone_name}: {title.get('ro') or 'lucrări'}",
                       en=f"{zone_name}: {title.get('en') or title.get('ro') or 'works'}"),
            body=I18n(ro=body["ro"], en=body["en"]),
            stopIds=stop_ids,
            routeIds=route_ids,
            alertIds=alert_ids,
            publishedAt=(published or {}).get("publishedAt"),
        ))
    out.sort(key=lambda n: (-len(n.stopIds), n.zoneName))
    return out


def notices_for(closure_id: str) -> list[ZoneNotice]:
    closure, analysis = _load(closure_id)
    published = _published(closure_id) if closure.get("status") == "published" else None
    sig = _signature(closure, analysis, published)
    hit = _memo.get(closure_id)
    if hit and hit[0] == sig:
        return hit[1]
    notices = build_notices(closure, analysis, published)
    _memo[closure_id] = (sig, notices)
    return notices


def feed(at: datetime | None = None) -> list[ZoneNotice]:
    """Notices of every published closure whose window has not ended at `at` (default: the app's now)."""
    at = at or config.now()
    out: list[ZoneNotice] = []
    for cid in state.list_ids("published"):
        try:
            closure = state.read("closures", cid)
        except ValueError:
            continue
        if closure is None or closure.get("status") != "published":
            continue
        if parse_iso(closure["window"]["end"]) <= at:
            continue
        try:
            out.extend(notices_for(cid))
        except Exception:  # noqa: BLE001 - one broken closure must not empty the feed
            import logging

            logging.getLogger("reteaua_vie.m3").exception("notices failed for %s", cid)
    return out
