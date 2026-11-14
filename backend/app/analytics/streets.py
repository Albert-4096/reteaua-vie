"""R8: critical street sections (departures exposed + minutes lost) and L4: where public transport stands.

Section = the link between two consecutive stops of a line's most common trip pattern (straight line on the
map). Exposure = scheduled trips over the link on one GTFS service day. Minutes lost = the growth of the
delay over the link (`run_sec - sched_run_sec` of L0's segment runs, both ends observed), positive growth only,
summed over the recording. L4 = recorded reports of a vehicle standing still between stops, grouped in 100 m cells.
"""

from __future__ import annotations

import time
from collections import defaultdict

import numpy as np
import pandas as pd

from app.analytics import accessibility, crossings
from app.analytics.coverage import reference_date
from app.common import gtfs
from app.common.city import load_network
from app.common.geo import haversine_m, xy_to_lonlat
from app.common.timeutil import iso
from app.config import TZ
from app.models.base import I18n
from app.observed import store

MIN_RUNS = 20
STOP_DIST_M = 30
SPEED_MAX_MPS = 0.5
SIGNAL_M = 50
CELL_M = 100
SAMPLE_CAP_SEC = 60
TTL_SEC = 300

WORDING = I18n(ro="Estimare din datele live, nu raportul oficial.", en="Estimate from the live data, not the official report.")
METHOD_R8 = I18n(
    ro=("Tronson = legătura dintre două stații consecutive ale tiparului unei linii (linie dreaptă pe hartă). "
        "Plecări expuse = cursele planificate GTFS peste tronson într-o zi de serviciu (zi lucrătoare de referință). "
        "Minute pierdute = creșterea întârzierii pe tronson (run observat minus run planificat, din orarul observat "
        f"L0, ambele capete observate), doar creșterea pozitivă, însumată pe înregistrare; „neconcludent” sub "
        f"{MIN_RUNS} treceri. Fără trecere înregistrată: „necunoscut”, nu 0."),
    en="Section = link between consecutive stops. Exposure = scheduled trips over it. Minutes lost = positive growth of the delay.")
METHOD_L4 = I18n(
    ro=(f"Fiecare raport al unui vehicul care stă pe loc (viteză ≤ {SPEED_MAX_MPS} m/s, mutat sub 15 m față de raportul "
        f"precedent), în afara stațiilor (peste {STOP_DIST_M} m de orice stație, nu STOPPED_AT), pe celule de "
        f"{CELL_M} m. Durata unui raport = până la următorul, cel mult {SAMPLE_CAP_SEC} s. Cauză: „semafor la cel mult "
        f"{SIGNAL_M} m” dacă un semafor OSM e în rază, altfel „coadă / altă cauză”. Ponderea: plecările pe zi ale "
        "liniilor care au stat acolo."),
    en="Stationary vehicle reports away from stops (> 30 m), per 100 m cell, with the OSM signal within 50 m if any.")
CAVEAT = I18n(
    ro=("Estimare din datele live, nu raportul oficial; doar vineri după-amiază și weekend, fără extrapolare la zilele "
        "lucrătoare. Arată unde stau vehiculele, nu de ce, și nu atribuie vina nimănui."),
    en="Estimate from the live data; Friday afternoon and weekend only. Shows where vehicles stand, not why.")
_memo: dict = {}


def _cached(key, fn):
    stamp = store._stamp()
    hit = _memo.get(key)
    if hit and hit[1] == stamp and time.monotonic() - hit[0] < TTL_SEC:
        return hit[2]
    out = fn()
    _memo[key] = (time.monotonic(), stamp, out)
    return out


def _sections() -> tuple[dict, dict, str]:
    """({(a, b): {lines, dep}}, stop info, reference date) from the trip patterns and one service day."""
    from datetime import datetime, timedelta

    d = reference_date("weekday")
    f = gtfs.feed(d)
    start = datetime(d.year, d.month, d.day, tzinfo=TZ)
    counts = gtfs.count_by_key(start, start + timedelta(days=1))
    names = accessibility._route_names()
    out: dict[tuple[str, str], dict] = defaultdict(lambda: {"routes": set(), "dep": 0})
    for p in gtfs.stop_patterns().values():
        for a, b in zip(p.stop_ids, p.stop_ids[1:]):
            s = out[(a, b)]
            s["routes"].add(p.route_id)
            s["dep"] += counts.get((a, p.route_id, p.direction_id), 0)
    st = f.stops.set_index("stop_id")
    info = {sid: (str(r.stop_name), float(r.stop_lon), float(r.stop_lat)) for sid, r in st.iterrows()}
    return dict(out), {"names": names, "info": info}, d.isoformat()


def critical_streets() -> dict:
    return _cached("streets", _critical)


def _critical() -> dict:
    cov = store.coverage()
    if cov is None:
        raise RuntimeError("L0 has no built hour yet (în lucru)")
    secs, aux, day = _sections()
    names, info = aux["names"], aux["info"]
    seg = store.segments()
    seg = seg[(~seg["from_interpolated"].astype(bool)) & (~seg["to_interpolated"].astype(bool))
              & (seg["run_sec"] > 0) & (seg["sched_run_sec"] > 0)].copy()
    seg["growth"] = seg["run_sec"] - seg["sched_run_sec"]
    seg["lost"] = seg["growth"].clip(lower=0)
    g = seg.groupby(["from_stop_id", "to_stop_id"]).agg(runs=("growth", "size"), lost=("lost", "sum"),
                                                        med=("growth", "median"))
    hours = max(1.0, (cov["last"] - cov["first"]).total_seconds() / 3600)
    rows = []
    for (a, b), s in secs.items():
        if a not in info or b not in info:
            continue
        m = g.loc[(a, b)] if (a, b) in g.index else None
        runs = int(m["runs"]) if m is not None else 0
        lost = round(float(m["lost"]) / 60, 1) if m is not None else None
        rows.append({
            "id": f"{a}>{b}", "fromStop": {"stopId": a, "name": info[a][0]}, "toStop": {"stopId": b, "name": info[b][0]},
            "lengthMeters": int(round(haversine_m(info[a][1], info[a][2], info[b][1], info[b][2]), -1)),
            "lines": sorted({names.get(r, (r, ""))[0] for r in s["routes"]}), "departuresPerDay": int(s["dep"]),
            "runs": runs, "lostMin": lost, "lostMinPerHour": round(lost / hours, 2) if lost is not None else None,
            "medianGrowthSec": round(float(m["med"]), 1) if m is not None else None,
            "conclusive": runs >= MIN_RUNS, "rank": None})
    ok = sorted((r for r in rows if r["conclusive"]), key=lambda r: -(r["lostMin"] or 0))
    for k, r in enumerate(ok, 1):
        r["rank"] = k
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, -r["departuresPerDay"], r["id"]))
    return {"recording": accessibility.recording_info(cov["first"], cov["last"]), "date": day, "minRuns": MIN_RUNS,
            "sections": rows, "wording": WORDING.model_dump(), "method": METHOD_R8.model_dump(),
            "caveat": CAVEAT.model_dump(),
            "provenance": [p.model_dump() for p in accessibility.provenances(cov["first"], cov["last"], "orar observat L0")]}


def layer(limit: int | None = None) -> dict:
    d = critical_streets()
    info = _sections()[1]["info"]
    feats = []
    for r in d["sections"][:limit]:
        a, b = info[r["fromStop"]["stopId"]], info[r["toStop"]["stopId"]]
        props = {k: r[k] for k in ("id", "lines", "departuresPerDay", "runs", "lostMin", "lostMinPerHour",
                                   "medianGrowthSec", "conclusive", "rank")}
        props["name"] = f"{a[0]} → {b[0]}"
        feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[a[1], a[2]], [b[1], b[2]]]},
                      "properties": props})
    return {"type": "FeatureCollection", "layer": "streets", "features": feats, "provenance": d["provenance"]}


def standing() -> dict:
    return _cached("standing", _standing)


def _standing() -> dict:
    cov = store.coverage()
    if cov is None:
        raise RuntimeError("L0 has no built hour yet (în lucru)")
    r = store.reports().sort_values(["vid", "t"]).reset_index(drop=True)
    nxt = r.groupby("vid")["t"].shift(-1)
    r["dur"] = (nxt - r["t"]).clip(upper=SAMPLE_CAP_SEC).fillna(0)
    moved = np.hypot(r["x"] - r["x"].shift(), r["y"] - r["y"].shift())
    still = (r["vid"] == r["vid"].shift()) & (moved < 15) & (r["speed"].astype(float) <= SPEED_MAX_MPS) \
        & (~r["stopped"].astype(bool)) & (r["dur"] > 0)
    net = load_network()
    sxy = net.stop_xy
    cand = r[still].copy()
    near = np.full(len(cand), np.inf)
    xy = cand[["x", "y"]].to_numpy()
    for lo in range(0, len(cand), 5000):
        c = xy[lo:lo + 5000]
        near[lo:lo + 5000] = np.hypot(c[:, None, 0] - sxy[None, :, 0], c[:, None, 1] - sxy[None, :, 1]).min(axis=1)
    cand["near"] = near
    cand = cand[cand["near"] > STOP_DIST_M]
    cand["cx"] = (cand["x"] // CELL_M).astype(int)
    cand["cy"] = (cand["y"] // CELL_M).astype(int)
    cand["hour"] = pd.to_datetime(cand["t"], unit="s", utc=True).dt.tz_convert(TZ).dt.hour
    cand["day"] = pd.to_datetime(cand["t"], unit="s", utc=True).dt.tz_convert(TZ).dt.date
    d = reference_date("weekday")
    from datetime import datetime, timedelta
    start = datetime(d.year, d.month, d.day, tzinfo=TZ)
    counts = gtfs.count_by_key(start, start + timedelta(days=1))
    dep_route: dict[str, int] = defaultdict(int)
    for p in gtfs.stop_patterns().values():
        dep_route[p.route_id] += counts.get((p.stop_ids[0], p.route_id, p.direction_id), 0)
    names = accessibility._route_names()
    sig = crossings.signals()
    hours = max(1.0, (cov["last"] - cov["first"]).total_seconds() / 3600)
    pts = []
    for (cx, cy), g in cand.groupby(["cx", "cy"]):
        minutes = float(g["dur"].sum()) / 60
        centre = ((cx + 0.5) * CELL_M, (cy + 0.5) * CELL_M)
        near_sig = bool(len(sig) and np.hypot(sig[:, 0] - centre[0], sig[:, 1] - centre[1]).min() <= SIGNAL_M + CELL_M / 2)
        routes = sorted({x for x in g["route"] if x})
        lon, lat = xy_to_lonlat(*centre)
        pts.append({"cellId": f"{cx}_{cy}", "location": [round(lon, 6), round(lat, 6)], "minutes": round(minutes, 1),
                    "minutesPerHour": round(minutes / hours, 2), "samples": int(len(g)), "vehicles": int(g["vid"].nunique()),
                    "days": int(g["day"].nunique()), "lines": [names.get(x, (x, ""))[0] for x in routes],
                    "departuresPerDay": int(sum(dep_route.get(x, 0) for x in routes)) if routes else None,
                    "nearestStopMeters": int(g["near"].min()),
                    "cause": "semafor la cel mult 50 m" if near_sig else "coadă / altă cauză",
                    "hours": {str(int(h)): round(float(v) / 60, 1) for h, v in g.groupby("hour")["dur"].sum().items()}})
    pts.sort(key=lambda p: -p["minutes"])
    return {"recording": accessibility.recording_info(cov["first"], cov["last"]), "date": d.isoformat(),
            "stopDistanceMeters": STOP_DIST_M, "speedMaxMps": SPEED_MAX_MPS, "signalMeters": SIGNAL_M,
            "points": pts[:300], "totalMinutes": round(float(cand["dur"].sum()) / 60, 1),
            "wording": WORDING.model_dump(), "method": METHOD_L4.model_dump(), "caveat": CAVEAT.model_dump(),
            "provenance": [p.model_dump() for p in accessibility.provenances(cov["first"], cov["last"], "orar observat L0")]
            + [crossings.provenance().model_dump()]}
