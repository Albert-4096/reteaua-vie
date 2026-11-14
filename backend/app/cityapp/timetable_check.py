"""R27: does the City Hall's own stop timetable still list departures that our published closure removes?

Reads cont.primariatm.ro/api/mobile/transit/stops/{id}/timetable?date= (public, GET, no key), one call per
stop per date, cached under $DATA_DIR/cache/city-timetable/, at most MAX_CALLS fresh calls per request.
CityApp receives our alert; this only lists what is left to mark. We never say CityApp is wrong."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import httpx

from app.common import state
from app.common import provenance as prov
from app.common.city import load_network
from app.common.errors import not_found
from app.common.timeutil import iso, local_midnight, parse_iso
from app.config import TZ, get_settings, real_now
from app.m1_disruption import impact as imp
from app.models.base import I18n, Provenance

URL = "https://cont.primariatm.ro/api/mobile/transit/stops/{stop}/timetable?date={day}"
USER_AGENT = "ReteauaVie/1.0 (UniHack 8, team The Bloom)"
MAX_CALLS = 30           # per request: the budget agreed for one publish
TIMEOUT = 8.0            # seconds per call
LABEL = "orar din API-ul Primăriei"


def _get(stop_id: str, day: date) -> dict:
    """One GET over IPv4 (this host has no IPv6 route; urllib would wait the timeout per AAAA address)."""
    with httpx.Client(transport=httpx.HTTPTransport(local_address="0.0.0.0"), timeout=TIMEOUT,
                      headers={"User-Agent": USER_AGENT}) as c:
        r = c.get(URL.format(stop=stop_id, day=day.isoformat()))
        r.raise_for_status()
        return r.json()


def _cache_path(stop_id: str, day: date):
    return get_settings().cache_dir / "city-timetable" / day.isoformat() / f"{stop_id}.json"


def stop_timetable(stop_id: str, day: date, budget: list[int]) -> dict | None:
    """The City Hall timetable of a stop for a day: from the cache, else one call (decrements budget[0]).
    None when the budget is spent or the call fails (nothing is cached then)."""
    p = _cache_path(stop_id, day)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            pass
    if budget[0] <= 0:
        return None
    budget[0] -= 1
    try:
        data = _get(stop_id, day)
    except (httpx.HTTPError, OSError, ValueError):
        return None
    if not isinstance(data.get("lines"), list):
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return data


def _times_in_window(times: list[str], day: date, start: datetime, end: datetime) -> int:
    """Count "HH:MM" times of one service day inside [start, end); a time earlier than the one before it is after midnight."""
    n, base, prev = 0, local_midnight(day), -1
    for t in times:
        try:
            h, m = (int(x) for x in t.split(":")[:2])
        except ValueError:
            continue
        minutes = h * 60 + m
        if minutes < prev:
            base += timedelta(days=1)
        prev = minutes
        if start <= base + timedelta(minutes=minutes) < end:
            n += 1
    return n


def _sentence(stops: int, listed: int, checked: int) -> I18n:
    if checked == 0:
        return I18n(ro="Orarul din API-ul Primăriei nu a putut fi citit acum: necunoscut.",
                    en="The City Hall timetable could not be read right now: unknown.")
    if listed == 0:
        return I18n(
            ro=f"CityApp primește alerta pentru {stops} stații; orarul lor din API-ul Primăriei nu mai listează plecări în fereastră: nimic de marcat.",
            en=f"CityApp receives the alert for {stops} stops; their timetable in the City Hall API lists no departures in the window: nothing to mark.")
    return I18n(
        ro=f"CityApp primește alerta pentru {stops} stații; orarul lor din API-ul Primăriei listează {listed} plecări în fereastră, de marcat.",
        en=f"CityApp receives the alert for {stops} stops; their timetable in the City Hall API lists {listed} departures in the window, to be marked.")


def check(closure_id: str, day: date | None = None) -> dict:
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    analysis = state.read("closures", closure_id, state.PART_ANALYSIS) if closure else None
    if closure is None or analysis is None:
        raise not_found(f"No analyzed closure {closure_id}.")
    day = day or real_now().date()
    d0 = local_midnight(day)
    w_start, w_end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    in_force = closure.get("status") == "published" and w_start < d0 + timedelta(days=1) and w_end > d0
    base = {"closureId": closure_id, "date": day.isoformat(), "inForce": in_force, "label": LABEL}
    if not in_force:
        return {**base, "state": "not_in_force", "stopsTotal": 0, "stopsChecked": 0, "stopsListing": 0,
                "departuresListed": 0, "items": [], "capped": False,
                "sentence": I18n(ro="Verificarea rulează doar pentru lucrări publicate și în vigoare în ziua aleasă.",
                                 en="The check runs only for published works in force on the chosen day."),
                "provenance": []}
    lo, hi = max(w_start, d0), min(w_end, d0 + timedelta(days=2))   # the day and its after-midnight tail
    lost: dict[str, list[dict]] = {}
    for row in analysis["stops"]:
        if imp.counts_as_lost(row):
            lost.setdefault(row["stopId"], []).append(row)
    stop_ids = sorted(lost)
    net, budget = load_network(), [MAX_CALLS]
    items, checked, listing, total = [], 0, 0, 0
    for sid in stop_ids:
        tt = stop_timetable(sid, day, budget)
        if tt is None:
            continue
        checked += 1
        listed_here = 0
        for row in lost[sid]:
            for ln in tt["lines"]:
                if ln.get("routeId") == row["routeId"] and int(ln.get("directionId", -1)) == int(row["directionId"]):
                    n = _times_in_window(ln.get("times") or [], day, lo, hi)
                    if n:
                        items.append({"stopId": sid, "name": (net.stop_by_id.get(sid) or {}).get("name", sid),
                                      "routeId": row["routeId"], "shortName": row.get("routeShortName") or row["routeId"],
                                      "directionId": int(row["directionId"]), "departuresListed": n})
                        listed_here += n
        total += listed_here
        listing += 1 if listed_here else 0
    sources: list[Provenance] = [prov.provenance(
        f"Primăria Timișoara, {LABEL} / City Hall API timetable", iso(real_now()),
        "https://cont.primariatm.ro/api/mobile/transit/stops/{stopId}/timetable", None,
        f"un apel pe stație și zi, memorat; cel mult {MAX_CALLS} apeluri noi pe cerere; {checked} din {len(stop_ids)} stații citite")]
    return {**base, "state": "ok" if checked else "unavailable", "stopsTotal": len(stop_ids), "stopsChecked": checked,
            "stopsListing": listing, "departuresListed": total, "items": items,
            "capped": checked < len(stop_ids), "sentence": _sentence(len(stop_ids), total, checked),
            "provenance": sources}
