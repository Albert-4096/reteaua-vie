"""C2: „în serviciu, fără date GPS (confirmat de N călători)”.

A trip is confirmed when at least MIN_TRAVELERS distinct phones checked in on it within WITHIN, while our
live recording shows no vehicle on that trip or on its line in that window (and the recording has data there:
no snapshot, no claim). Thresholds are proposals, not measured. Presence proves; absence proves nothing."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.checkin import store
from app.checkin.models import ServiceConfirmation
from app.common.timeutil import iso, parse_iso
from app.live import missing
from app.models.base import I18n

MIN_TRAVELERS = 2
WITHIN = timedelta(minutes=10)
PAD = timedelta(minutes=10)     # the recording is read this far around the check-ins


def _label(n: int, simulated: bool) -> I18n:
    ro = f"în serviciu, fără date GPS (confirmat de {n} călători)" + (" · simulare" if simulated else "")
    en = f"in service, no GPS data (confirmed by {n} travellers)" + (" · simulation" if simulated else "")
    return I18n(ro=ro, en=en)


def confirmations(start: datetime, end: datetime) -> dict[str, ServiceConfirmation]:
    """{routeId: ServiceConfirmation} for check-ins with `at` in [start, end)."""
    by_trip: dict[tuple[str, str], list[dict]] = {}
    for r in store.raw_rows():
        t = parse_iso(r["at"])
        if start <= t < end:
            by_trip.setdefault((r["routeId"], r["tripId"]), []).append({**r, "t": t})
    out: dict[str, dict] = {}
    for (route, trip), rows in by_trip.items():
        rows.sort(key=lambda r: r["t"])
        best: list[dict] = []
        for i, r in enumerate(rows):
            grp = [x for x in rows[i:] if x["t"] - r["t"] <= WITHIN]
            if len({x["device"] for x in grp}) > len({x["device"] for x in best}):
                best = grp
        devices = {x["device"] for x in best}
        if len(devices) < MIN_TRAVELERS:
            continue
        lo, hi = best[0]["t"], best[-1]["t"]
        snaps, _ = missing.recorded(lo - PAD, hi + PAD)
        if not snaps:                    # no recording there: we cannot say „fără date GPS”
            continue
        if any(route in s.routes or trip in s.trips for s in snaps):
            continue                     # a vehicle of the line was seen: not this state
        o = out.setdefault(route, {"travelers": 0, "trips": [], "first": lo, "last": hi, "sim": False})
        o["travelers"] = max(o["travelers"], len(devices))
        o["trips"].append(trip)
        o["first"], o["last"] = min(o["first"], lo), max(o["last"], hi)
        o["sim"] = o["sim"] or any(x["simulated"] for x in best)
    return {r: ServiceConfirmation(travelers=o["travelers"], trips=sorted(o["trips"]), firstAt=iso(o["first"]),
                                   lastAt=iso(o["last"]), simulated=o["sim"], label=_label(o["travelers"], o["sim"]))
            for r, o in out.items()}


def annotate(rows: list[dict], window: dict) -> list[dict]:
    """Rows of MissingLines + `serviceConfirmation` (additive; `state` is not changed)."""
    conf = confirmations(parse_iso(window["start"]), parse_iso(window["end"]))
    return [{**r, "serviceConfirmation": conf[r["routeId"]].model_dump() if r["routeId"] in conf else None} for r in rows]
