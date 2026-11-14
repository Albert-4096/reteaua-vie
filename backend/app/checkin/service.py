"""C1 logic: accept a check-in, aggregate counts."""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timedelta

from app.checkin import resolve, store
from app.checkin.models import (CheckinAck, CheckinCounts, CheckinInput, LineCheckins, StopCount, TripCount)
from app.common import provenance as prov
from app.common.city import load_network
from app.common.errors import ApiError, invalid, not_found
from app.common.timeutil import iso, parse_iso
from app.config import TZ, real_now
from app.models.base import I18n, Provenance

MAX_PER_MIN = 120          # overall, like R7
MAX_PER_STICKER_MIN = 20   # per sticker, like R7
MAX_PER_DEVICE_MIN = 6
WINDOW_SEC = 60.0
FUTURE_SLACK = timedelta(minutes=2)

SIM_LABEL = I18n(ro="simulare", en="simulation")
_lock = threading.Lock()
_all: deque[float] = deque()
_by: dict[str, deque[float]] = {}


def allow(sticker: str, device: str, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    with _lock:
        cutoff = now - WINDOW_SEC
        while _all and _all[0] < cutoff:
            _all.popleft()
        for k in [k for k, q in _by.items() if not q or q[-1] < cutoff]:
            del _by[k]
        qs, qd = _by.setdefault("s:" + sticker, deque()), _by.setdefault("d:" + device, deque())
        for q in (qs, qd):
            while q and q[0] < cutoff:
                q.popleft()
        if len(_all) >= MAX_PER_MIN or len(qs) >= MAX_PER_STICKER_MIN or len(qd) >= MAX_PER_DEVICE_MIN:
            return False
        _all.append(now)
        qs.append(now)
        qd.append(now)
        return True


def _prov(simulated: bool) -> list[Provenance]:
    return [prov.provenance(
        "Rețeaua Vie, check-in la bord (numărătoare paralelă, nu validare oficială)", iso(real_now()), None, None,
        "fără IP, agent, cont sau nume; poziția folosită doar la momentul check-in-ului și nepăstrată; telefonul = "
        "hash cu sare zilnică; rânduri păstrate 48 h, apoi doar numere; pragurile (300 m de traseu, 2 telefoane în "
        "10 min) sunt propuneri, nemăsurate" + ("; autocolant de test: simulare, atingerile sunt reale" if simulated else ""))]


def accept(body: CheckinInput) -> CheckinAck:
    reg = store.stickers()
    sticker = reg.get(body.stickerId)
    if sticker is None:
        raise not_found(f"Autocolant necunoscut: {body.stickerId}.", code="NO_SUCH_STICKER")
    if (body.lat is None) != (body.lon is None):
        raise invalid("`lat` și `lon` merg împreună.")
    received = real_now()
    try:
        at = parse_iso(body.at) if body.at else received
    except ValueError:
        raise invalid("`at` must be an ISO 8601 time") from None
    if at > received + FUTURE_SLACK:
        raise invalid("`at` este în viitor.")
    if at < received - store.RETENTION:
        raise invalid("`at` este mai vechi de 48 h: nu mai păstrăm rânduri.")
    device = store.device_hash(body.deviceKey, received)
    if not allow(body.stickerId, device):
        raise ApiError(429, "RATE_LIMITED", "Prea multe check-in-uri, încearcă peste un minut.")
    route, direction = sticker["routeId"], int(sticker["directionId"])
    r = resolve.resolve(route, direction, at, body.lat, body.lon)
    simulated = bool(sticker.get("simulated"))
    store.add_row({"at": iso(at), "receivedAt": iso(received), "stickerId": body.stickerId, "routeId": route,
                   "directionId": direction, "tripId": r["tripId"], "stopId": r["stopId"], "device": device,
                   "simulated": simulated}, received)
    short = (load_network().route_by_id.get(route) or {}).get("shortName")
    return CheckinAck(routeId=route, shortName=short, directionId=direction, tripId=r["tripId"], stopId=r["stopId"],
                      stopName=r["stopName"], method=r["method"], distanceToRouteMeters=r["distanceToRouteMeters"],
                      at=iso(at), simulated=simulated, label=SIM_LABEL if simulated else None, provenance=_prov(simulated))


def counts(start: datetime, end: datetime, route_id: str | None = None) -> CheckinCounts:
    net = load_network()
    lines: dict[str, dict] = {}

    def line(r: str) -> dict:
        return lines.setdefault(r, {"trips": {}, "stops": {}, "total": 0, "simulated": 0})

    for r in store.raw_rows():
        if route_id and r["routeId"] != route_id:
            continue
        t = parse_iso(r["at"])
        if not (start <= t < end):
            continue
        ln = line(r["routeId"])
        tr = ln["trips"].setdefault(r["tripId"], {"count": 0, "devices": set(), "simulated": 0, "first": r["at"], "last": r["at"]})
        tr["count"] += 1
        tr["devices"].add(r["device"])
        tr["simulated"] += 1 if r["simulated"] else 0
        tr["first"], tr["last"] = min(tr["first"], r["at"]), max(tr["last"], r["at"])
        if r.get("stopId"):
            s = ln["stops"].setdefault(r["stopId"], {"count": 0, "simulated": 0})
            s["count"] += 1
            s["simulated"] += 1 if r["simulated"] else 0
        ln["total"] += 1
        ln["simulated"] += 1 if r["simulated"] else 0
    for day, by_route in store.archived_counts().items():    # older than 48 h: counts only
        if not (start.date().isoformat() <= day <= end.date().isoformat()):
            continue
        for rid, trips in by_route.items():
            if route_id and rid != route_id:
                continue
            ln = line(rid)
            for trip, c in trips.items():
                tr = ln["trips"].setdefault(trip, {"count": 0, "devices": None, "simulated": 0, "first": None, "last": None})
                tr["count"] += c["count"]
                tr["simulated"] += c["simulated"]
                ln["total"] += c["count"]
                ln["simulated"] += c["simulated"]
                for sid, n in c.get("stops", {}).items():
                    s = ln["stops"].setdefault(sid, {"count": 0, "simulated": 0})
                    s["count"] += n
    out = []
    for rid, ln in sorted(lines.items()):
        out.append(LineCheckins(
            routeId=rid, shortName=(net.route_by_id.get(rid) or {}).get("shortName"), total=ln["total"],
            simulated=ln["simulated"],
            trips=[TripCount(tripId=t, count=v["count"], distinctDevices=None if v["devices"] is None else len(v["devices"]),
                             simulated=v["simulated"], firstAt=v["first"], lastAt=v["last"])
                   for t, v in sorted(ln["trips"].items())],
            stops=[StopCount(stopId=s, stopName=(net.stop_by_id.get(s) or {}).get("name"), count=v["count"], simulated=v["simulated"])
                   for s, v in sorted(ln["stops"].items(), key=lambda kv: -kv[1]["count"])]))
    total = sum(x.total for x in out)
    sim = sum(x.simulated for x in out)
    note = I18n(ro="Numărătoare paralelă a check-in-urilor din vehicul, nu validare oficială. Prezența dovedește, absența nu."
                   + (" Includ atingeri printr-un autocolant de test: simulare." if sim else ""),
                en="A parallel count of on-board check-ins, not the official validation. Presence proves, absence does not."
                   + (" Includes taps through a test sticker: simulation." if sim else ""))
    return CheckinCounts(window={"start": iso(start), "end": iso(end)}, lines=out, total=total, simulated=sim,
                         note=note, provenance=_prov(bool(sim)))
