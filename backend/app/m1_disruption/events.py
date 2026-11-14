"""N2: City Hall events inside a closure's works window and within walking distance.

Source: our recording of the City Hall /api/mobile/events in $LIVE_DIR/events/*.json (one
file every 6 h; the newest file that holds an event wins). Nothing is fetched here.

An event is listed when its dates overlap the closure window and its venue lies within
WALK_METERS of the closed section (the closure geometry) or of a stop that loses service
(the rows the conflicts module counts as lost, `conflicts._lost`). A venue without
coordinates is not placed: it is counted in `withoutVenue` („necunoscut”). Events that run
longer than ONGOING_DAYS (exhibitions, weekly tours) are flagged `ongoing`, so the UI can
keep them apart from day events.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from shapely.geometry import Point

from app.common import state
from app.common import provenance as prov
from app.common.errors import not_found
from app.common.geo import to_metric
from app.common.timeutil import file_mtime, iso, parse_iso
from app.config import TZ, get_settings
from app.m1_disruption import conflicts as cf
from app.models.base import I18n, Model, Provenance, Window

WALK_METERS = 400.0
ONGOING_DAYS = 7
EVENTS_URL = "https://cont.primariatm.ro/api/mobile/events"


class EventNearest(Model):
    kind: str  # "stop" | "closure"
    stopId: str | None
    stopName: str | None
    meters: int


class EventHit(Model):
    id: str
    title: str
    category: str | None
    venue: str | None
    url: str | None
    dateStart: str
    dateEnd: str
    ongoing: bool
    overlap: Window
    nearest: EventNearest


class EventConflicts(Model):
    closureId: str
    window: Window
    walkMeters: int
    events: list[EventHit]
    inWindow: int
    nearby: int
    withoutVenue: int
    summary: I18n
    provenance: list[Provenance]


def events_dir() -> Path:
    return get_settings().live_dir / "events"


def _files() -> list[Path]:
    d = events_dir()
    return sorted(d.glob("*.json")) if d.is_dir() else []


@lru_cache(maxsize=2)
def _load(signature: tuple) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path_str, _s, _m in signature:  # oldest first, the newest file wins
        try:
            data = json.loads(Path(path_str).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for e in data.get("events", []) if isinstance(data, dict) else []:
            if e.get("id") and e.get("dateStart") and e.get("dateEnd"):
                out[str(e["id"])] = e
    return out


def load_events() -> dict[str, dict]:
    return _load(tuple((str(p), p.stat().st_size, p.stat().st_mtime) for p in _files()))


def _dt(ts: float) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(TZ)


def _closure(closure_id: str) -> dict:
    try:
        c = state.read("closures", closure_id)
    except ValueError:
        c = None
    if c is None:
        raise not_found(f"No closure {closure_id}.")
    return c


def events_for(closure_id: str) -> EventConflicts:
    closure = _closure(closure_id)
    analysis = state.read("closures", closure_id, state.PART_ANALYSIS)
    w0, w1 = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    geom = cf._buffered(dict(closure, bufferMeters=0)) if closure.get("geometry") else None
    lost = cf._lost(analysis)
    stops = [(s["stopId"], s.get("name") or "", to_metric(Point(*s["location"][:2])))
             for s in (analysis or {}).get("stops") or [] if s.get("stopId") in lost and s.get("location")]
    seen_stop: set[str] = set()
    uniq_stops = [x for x in stops if not (x[0] in seen_stop or seen_stop.add(x[0]))]

    in_window = without_venue = 0
    hits: list[EventHit] = []
    for e in load_events().values():
        s, f = _dt(e["dateStart"]), _dt(e["dateEnd"])
        start, end = max(s, w0), min(f, w1)
        if start > end:
            continue
        in_window += 1
        lat, lng = e.get("venueLat"), e.get("venueLng")
        if lat is None or lng is None:
            without_venue += 1
            continue
        p = to_metric(Point(float(lng), float(lat)))
        best: EventNearest | None = None
        if geom is not None:
            d = geom.distance(p)
            best = EventNearest(kind="closure", stopId=None, stopName=None, meters=int(round(d)))
        for sid, name, sp in uniq_stops:
            d = sp.distance(p)
            if best is None or d < best.meters:
                best = EventNearest(kind="stop", stopId=sid, stopName=name, meters=int(round(d)))
        if best is None or best.meters > WALK_METERS:
            continue
        hits.append(EventHit(
            id=str(e["id"]), title=e.get("title") or "", category=e.get("category"), venue=e.get("venue"),
            url=e.get("url") or e.get("detailsUrl"), dateStart=iso(s), dateEnd=iso(f),
            ongoing=(f - s).days > ONGOING_DAYS, overlap=Window(start=iso(start), end=iso(end)), nearest=best))
    hits.sort(key=lambda h: (h.ongoing, h.overlap.start, h.nearest.meters, h.id))

    day_events = sum(1 for h in hits if not h.ongoing)
    if not hits:
        ro = "Niciun eveniment cu locație cunoscută la mai puțin de 400 m în fereastra lucrării."
        en = "No event with a known venue within 400 m during the works window."
    else:
        ro = (f"{len(hits)} {'eveniment' if len(hits) == 1 else 'evenimente'} la mai puțin de 400 m în fereastra lucrării "
              f"({day_events} de o zi sau scurte, {len(hits) - day_events} de lungă durată).")
        en = (f"{len(hits)} {'event' if len(hits) == 1 else 'events'} within 400 m during the works window "
              f"({day_events} short, {len(hits) - day_events} long-running).")
    if without_venue:
        ro += f" {without_venue} fără locație: necunoscut."
        en += f" {without_venue} without a venue: unknown."
    files = _files()
    provs = [prov.for_file("Primăria Timișoara, evenimente (API CityApp), înregistrate de noi / City Hall events, our recording",
                           files[-1], EVENTS_URL, None, "înregistrare la 6 ore; distanța e în linie dreaptă")] if files else []
    return EventConflicts(closureId=closure_id, window=Window(start=iso(w0), end=iso(w1)), walkMeters=int(WALK_METERS),
                          events=hits, inWindow=in_window, nearby=len(hits), withoutVenue=without_venue,
                          summary=I18n(ro=ro, en=en), provenance=provs)
