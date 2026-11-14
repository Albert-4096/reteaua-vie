"""R20 logic. Same privacy model as the check-in: no account, name, IP or user agent; the phone is a salted daily
hash; the position (only if the rider taps) is used once to check the stop and is not kept; raw rows 48 h, then
counts only; fixed categories, no free text. Nothing is sent to the City Hall's Sesizări: we do not write to its API."""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timedelta

from app.checkin import store
from app.common import provenance as prov
from app.common.city import load_network
from app.common.errors import ApiError, invalid, not_found
from app.common.geo import haversine_m
from app.common.timeutil import iso
from app.config import TZ, real_now
from app.models.base import I18n, Provenance
from app.travellers.models import (CATEGORY_LABELS, CategoryCount, ReportAck, ReportInput, ReportSummary, StopReports,
                                   TravellerSignal)

MAX_PER_MIN = 120
MAX_PER_STOP_MIN = 20
MAX_PER_DEVICE_MIN = 4
DEDUPE = timedelta(minutes=10)
MAX_FROM_STOP_M = 300.0          # proposal: the rider is at the stop
SIGNAL_WINDOW = timedelta(hours=6)
WINDOW_SEC = 60.0
_lock = threading.Lock()
_all: deque[float] = deque()
_by: dict[str, deque[float]] = {}


def allow(stop: str, device: str, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    with _lock:
        cutoff = now - WINDOW_SEC
        while _all and _all[0] < cutoff:
            _all.popleft()
        for k in [k for k, q in _by.items() if not q or q[-1] < cutoff]:
            del _by[k]
        qs, qd = _by.setdefault("s:" + stop, deque()), _by.setdefault("d:" + device, deque())
        for q in (qs, qd):
            while q and q[0] < cutoff:
                q.popleft()
        if len(_all) >= MAX_PER_MIN or len(qs) >= MAX_PER_STOP_MIN or len(qd) >= MAX_PER_DEVICE_MIN:
            return False
        _all.append(now)
        qs.append(now)
        qd.append(now)
        return True


def _prov(note_extra: str = "") -> list[Provenance]:
    return [prov.provenance(
        "Rețeaua Vie, semnale de la călători (categorii fixe) / traveller signals", iso(real_now()), None, None,
        "un semnal, nu un fapt: neconfirmat de STPT sau Primărie; fără text liber, IP, agent, cont sau nume; telefon = hash cu "
        "sare zilnică; poziția (doar la apăsare) se folosește o dată și nu se păstrează; rânduri 48 h, apoi doar numere; nu "
        "trimitem nimic către Sesizări" + note_extra)]


# --- storage (the check-in's state dir and lock) ----------------------------------------------------------

def _name(received: datetime) -> str:
    return f"reports-{store._day(received)}.json"


def _files():
    return sorted(store._dir().glob("reports-*.json"))


def _purge(now: datetime) -> None:
    cutoff = now.astimezone(TZ) - store.RETENTION
    with store.locked():
        for p in _files():
            rows = store._read(p.name, [])
            old = [r for r in rows if datetime.fromisoformat(r["receivedAt"]) < cutoff]
            if not old:
                continue
            counts = store._read("reportcounts.json", {})
            for r in old:
                day = counts.setdefault(r["receivedAt"][:10], {}).setdefault(r["stopId"], {})
                day[r["category"]] = day.get(r["category"], 0) + 1
            store._write("reportcounts.json", counts)
            keep = [r for r in rows if r not in old]
            if keep:
                store._write(p.name, keep)
            else:
                p.unlink(missing_ok=True)


def rows() -> list[dict]:
    with store.locked():
        out: list[dict] = []
        for p in _files():
            out.extend(store._read(p.name, []))
        return out


def accept(body: ReportInput) -> ReportAck:
    stop = load_network().stop_by_id.get(body.stopId)
    if stop is None:
        raise not_found(f"Stație necunoscută: {body.stopId}.", code="NO_SUCH_STOP")
    if (body.lat is None) != (body.lon is None):
        raise invalid("`lat` și `lon` merg împreună.")
    if body.lat is not None:
        d = haversine_m(body.lon, body.lat, stop["location"][0], stop["location"][1])
        if d > MAX_FROM_STOP_M:
            raise invalid("Poziție departe de stație: semnalul nu e legat de această stație.", code="FAR_FROM_STOP")
    if body.routeId and body.routeId not in set(stop.get("routeIds") or []):
        raise invalid("Linia nu oprește la această stație.", code="ROUTE_NOT_AT_STOP")
    received = real_now()
    device = store.device_hash("report:" + body.deviceKey, received)
    if not allow(body.stopId, device):
        raise ApiError(429, "RATE_LIMITED", "Prea multe semnale, încearcă peste un minut.")
    dup = any(r["device"] == device and r["stopId"] == body.stopId and r["category"] == body.category
              and received - datetime.fromisoformat(r["receivedAt"]) < DEDUPE for r in rows())
    if not dup:
        with store.locked():
            n = _name(received)
            cur = store._read(n, [])
            cur.append({"receivedAt": iso(received), "stopId": body.stopId, "category": body.category,
                        "routeId": body.routeId, "device": device})
            store._write(n, cur)
        _purge(received)
    label = CATEGORY_LABELS[body.category]
    return ReportAck(stopId=body.stopId, stopName=stop["name"], category=body.category, label=label, counted=not dup,
                     note=I18n(ro="Mulțumim. E un semnal de la călători, nu o sesizare oficială: nu a fost trimis Primăriei. "
                                  "Pentru o sesizare oficială folosește aplicația Sesizări.",
                               en="Thank you. This is a traveller signal, not an official report: it was not sent to the City Hall. "
                                  "For an official report use the Sesizări app."),
                     provenance=_prov())


def summary(start: datetime, end: datetime, stop_id: str | None = None, route_id: str | None = None) -> ReportSummary:
    net = load_network()
    per: dict[str, dict[str, dict]] = {}
    for r in rows():
        t = datetime.fromisoformat(r["receivedAt"])
        if not (start <= t < end) or (stop_id and r["stopId"] != stop_id) or (route_id and r.get("routeId") != route_id):
            continue
        c = per.setdefault(r["stopId"], {}).setdefault(r["category"], {"devices": set(), "n": 0})
        c["devices"].add(r["device"])
        c["n"] += 1
    stops, total = [], set()
    for sid, cats in per.items():
        allp = set().union(*(c["devices"] for c in cats.values()))
        total |= {(sid, d) for d in allp}
        stops.append(StopReports(stopId=sid, stopName=(net.stop_by_id.get(sid) or {}).get("name"), travellers=len(allp),
                                 byCategory=[CategoryCount(category=k, label=CATEGORY_LABELS[k], travellers=len(v["devices"]), reports=v["n"])
                                             for k, v in sorted(cats.items())]))
    stops.sort(key=lambda s: (-s.travellers, s.stopId))
    return ReportSummary(window={"start": iso(start), "end": iso(end)}, stops=stops, travellers=len({d for _s, d in total}),
                         note=I18n(ro="Semnale de la călători, în categorii fixe: neconfirmate. Prezența arată o problemă posibilă, absența nu dovedește nimic.",
                                   en="Traveller signals in fixed categories: unconfirmed. Presence points to a possible problem, absence proves nothing."),
                         provenance=_prov())


def signal_for_stop(stop_id: str, at: datetime) -> TravellerSignal | None:
    s = summary(at - SIGNAL_WINDOW, at + timedelta(minutes=1), stop_id=stop_id)
    return _signal(s.stops[0].byCategory, s.stops[0].travellers, s.window) if s.stops else None


def signal_for_route(route_id: str, start: datetime, end: datetime) -> TravellerSignal | None:
    """O2: phones that said, for this line, that the bus did not come (or came although announced closed)."""
    s = summary(start, end, route_id=route_id)
    n = len({(x.stopId) for x in s.stops})
    if not s.stops:
        return None
    travellers = s.travellers
    cats: dict[str, int] = {}
    for st in s.stops:
        for c in st.byCategory:
            cats[c.category] = cats.get(c.category, 0) + c.travellers
    return TravellerSignal(travellers=travellers, byCategory=cats, window=s.window, label=_label(travellers))


def _label(n: int) -> I18n:
    return I18n(ro=f"semnalat de {n} {'călător' if n == 1 else 'călători'} (neconfirmat)",
                en=f"reported by {n} {'traveller' if n == 1 else 'travellers'} (unconfirmed)")


def _signal(cats: list[CategoryCount], travellers: int, window: dict) -> TravellerSignal:
    return TravellerSignal(travellers=travellers, byCategory={c.category: c.travellers for c in cats}, window=window,
                           label=_label(travellers))
