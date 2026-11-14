"""R9: where public transport waits at signals (per OSM signal) and the signals on a closure's detour.

Built on L4 (`app.analytics.streets.standing()`, called, not copied): its 100 m cells whose cause is „semafor la
cel mult 50 m” are attributed to the nearest OSM `highway=traffic_signals` node. Vehicle-minutes add up over every
vehicle that stood there, so the ranking is weighted by the traffic that really passes. For a closure, the signals
within 25 m of each detour path (L2's `detourPath`) are listed as candidates for a signal-phase check or priority:
a proposal for the traffic department, never a measured saving."""

from __future__ import annotations

import numpy as np
from pydantic import Field
from shapely.geometry import LineString, Point

from app.analytics import crossings, streets
from app.common import provenance as prov
from app.common.city import load_network
from app.common.geo import project_lonlats, to_metric, xy_to_lonlat
from app.common.timeutil import iso, parse_iso
from app.config import now
from app.m1_disruption import impact as imp
from app.models.base import I18n, Model, Provenance

ATTRIBUTE_M = streets.SIGNAL_M + streets.CELL_M / 2     # the same rule L4 uses to say „semafor”
ON_PATH_M = 25.0

LABEL = I18n(ro="măsurat din înregistrare, eșantion la 15 s; nu e simulare. Plafon: timpul măsurat în așteptare, nu o economie promisă.",
             en="measured from the recording, 15 s samples; not a simulation. Ceiling: the measured waiting time, not a promised saving.")
PROPOSAL = I18n(ro="Propunere pentru serviciul de trafic: verificarea fazelor sau prioritate pentru liniile deviate. Nu propunem durate de semnal.",
                en="A proposal for the traffic department: check the phases or give priority to the detoured lines. We propose no signal timings.")


class SignalWait(Model):
    signalId: str
    location: list[float]
    nearStop: str | None             # the nearest stop within 150 m, to name the junction
    minutes: float                   # vehicle-minutes standing, over the recording
    minutesPerHour: float
    samples: int
    vehicles: int
    lines: list[str]
    departuresPerDay: int | None     # the busiest attributed cell's lines, GTFS departures per service day
    cells: int


class SignalWaits(Model):
    recording: dict
    date: str
    signals: list[SignalWait]
    totalMinutes: float              # at all attributed signals
    label: I18n
    method: I18n
    provenance: list[Provenance]


class DetourSignal(Model):
    signalId: str
    location: list[float]
    nearStop: str | None
    lines: list[str]                 # the detoured lines whose path passes here
    departuresInWindow: int          # GTFS departures of those lines in the closure's window, at the stop where each detour starts
    standingMinutes: float | None    # measured standing at this signal (recording); null = „necunoscut”
    standingNote: str


class DetourSignals(Model):
    closureId: str
    status: str                      # ok | fara_ocolire | fara_inregistrare | in_lucru
    signals: list[DetourSignal]
    note: I18n | None
    proposal: I18n
    method: I18n
    provenance: list[Provenance]


def _signal_table():
    xy = crossings.signals()
    ll = [xy_to_lonlat(float(x), float(y)) for x, y in xy]
    ids = [f"sig_{lat:.5f}_{lon:.5f}" for lon, lat in ll]
    return xy, ll, ids


def _near_stop(x: float, y: float) -> str | None:
    net = load_network()
    d = np.hypot(net.stop_xy[:, 0] - x, net.stop_xy[:, 1] - y)
    i = int(np.argmin(d))
    return net.stop_by_id[net.stop_ids[i]]["name"] if d[i] <= 150 else None


def ranking(limit: int = 30) -> SignalWaits:
    st = streets.standing()
    xy, ll, ids = _signal_table()
    agg: dict[int, dict] = {}
    for p in st["points"]:
        if not p["cause"].startswith("semafor") or not len(xy):
            continue
        cx, cy = project_lonlats([tuple(p["location"])])[0]
        d = np.hypot(xy[:, 0] - cx, xy[:, 1] - cy)
        i = int(np.argmin(d))
        if d[i] > ATTRIBUTE_M:
            continue
        a = agg.setdefault(i, {"minutes": 0.0, "mph": 0.0, "samples": 0, "veh": 0, "lines": set(), "dep": None, "cells": 0})
        a["minutes"] += p["minutes"]
        a["mph"] += p["minutesPerHour"]
        a["samples"] += p["samples"]
        a["veh"] += p["vehicles"]
        a["lines"] |= set(p["lines"])
        a["cells"] += 1
        if p.get("departuresPerDay") is not None:
            a["dep"] = max(a["dep"] or 0, p["departuresPerDay"])
    rows = [SignalWait(signalId=ids[i], location=[round(ll[i][0], 6), round(ll[i][1], 6)], nearStop=_near_stop(*xy[i]),
                       minutes=round(a["minutes"], 1), minutesPerHour=round(a["mph"], 2), samples=a["samples"],
                       vehicles=a["veh"], lines=sorted(a["lines"]), departuresPerDay=a["dep"], cells=a["cells"])
            for i, a in agg.items()]
    rows.sort(key=lambda r: -r.minutes)
    method = I18n(ro=("Celulele L4 de 100 m cu „semafor la cel mult 50 m” sunt atribuite celui mai apropiat semafor OSM "
                      "(highway=traffic_signals, la cel mult 100 m). Minutele sunt vehicul-minute adunate peste toate vehiculele "
                      "care au stat acolo, deci ordinea e ponderată de traficul real; plecările pe zi sunt ale celei mai active celule. "
                      "Doar vineri după-amiază și weekend; fără extrapolare."),
                  en=("L4's 100 m cells with „signal within 50 m” are attributed to the nearest OSM signal (highway=traffic_signals, "
                      "within 100 m). Minutes are vehicle-minutes summed over every vehicle that stood there, so the order is weighted "
                      "by real traffic; departures per day are those of the busiest cell. Friday afternoon and weekend only; no extrapolation."))
    return SignalWaits(recording=st["recording"], date=st["date"], signals=rows[:limit],
                       totalMinutes=round(sum(r.minutes for r in rows), 1), label=LABEL, method=method,
                       provenance=[Provenance(**p) if isinstance(p, dict) else p for p in st["provenance"]])


def on_detour(closure_id: str) -> DetourSignals:
    from app.common import state
    from app.observed import window_cost

    method = I18n(ro=(f"Semafoarele OSM (highway=traffic_signals) la cel mult {ON_PATH_M:.0f} m de traseul de ocolire al fiecărei linii "
                      "(L2, străzile fără bară de trafic). Plecările sunt cele ale liniei din GTFS, în fereastra lucrării, la stația unde începe ocolul. "
                      "Așteptarea măsurată vine din înregistrare (R9a) sau e „necunoscut”."),
                  en=(f"OSM signals within {ON_PATH_M:.0f} m of each line's detour path (L2). Departures are the line's GTFS departures in the closure's window "
                      "at the stop where its detour starts. Measured waiting comes from the recording (R9a) or is „unknown”."))

    def out(status, signals, note=None, extra=()):
        return DetourSignals(closureId=closure_id, status=status, signals=signals, note=note, proposal=PROPOSAL, method=method,
                             provenance=[prov.provenance("Rețeaua Vie R9, semafoare pe ocolire / signals on the detour", iso(now()), None, None,
                                                         "propunere pentru serviciul de trafic; OSM + L2 + GTFS"), *extra])

    mw = window_cost.suggest(closure_id)
    if mw.status == "fara_inregistrare":
        return out("fara_inregistrare", [], I18n(ro="Nu avem încă înregistrare pentru drumurile de ocolire.", en="No recording yet for the detour roads."))
    paths = [(l, LineString(l.detourPath["coordinates"])) for l in mw.lines if l.detourPath]
    if not paths:
        return out("fara_ocolire", [], I18n(ro="Nicio linie nu are un drum de ocolire calculat.", en="No line has a computed detour path."))
    closure = state.read("closures", closure_id)
    tt = imp.timetable_for_closure(closure)
    cw = imp.count_window(parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"]), tt)
    counts = imp.departure_counts(cw, tt) or {}
    # departures of each detoured line in the closure's window, at the stop where its detour starts (GTFS)
    lost = {(l.routeId, l.directionId): counts.get((l.fromStopId, l.routeId, l.directionId), 0) for l, _g in paths}
    xy, ll, ids = _signal_table()
    try:
        waits = {w.signalId: w for w in ranking(300).signals}
    except Exception:
        waits = {}
    found: dict[int, dict] = {}
    for line, geom in paths:
        g = to_metric(geom)
        for i, (x, y) in enumerate(xy):
            if g.distance(Point(x, y)) <= ON_PATH_M:
                f = found.setdefault(i, {"lines": set(), "dep": {}})
                f["lines"].add(line.shortName)
                f["dep"][(line.routeId, line.directionId)] = lost.get((line.routeId, line.directionId), 0)
    sig = []
    for i, f in found.items():
        w = waits.get(ids[i])
        sig.append(DetourSignal(signalId=ids[i], location=[round(ll[i][0], 6), round(ll[i][1], 6)], nearStop=_near_stop(*xy[i]),
                                lines=sorted(f["lines"]), departuresInWindow=sum(f["dep"].values()),
                                standingMinutes=w.minutes if w else None,
                                standingNote="măsurat din înregistrare" if w else "necunoscut (fără celulă măsurată la acest semafor)"))
    sig.sort(key=lambda s: (-(s.standingMinutes or 0), -s.departuresInWindow, s.signalId))
    return out("ok", sig)
