"""R24: works balance, planned vs measured, one row per closure (step 5).

Only existing modules, each figure with its source and the recording window label:
  stops      the live check (`app.live.check`): suspended stops the vehicles skipped or served anyway;
  spillover  `app.m4_access.spillover` on the detour-load edges: delay on those streets vs the rest of the network;
  sesizari   `app.live.reports`: reports within 500 m during the window vs the 7 days before (counts per day);
  o2         `app.live.missing` (O2): trips of the affected lines with no vehicle in the live data;
  l3         `app.analytics.reliability` (L3): on-time share of the affected lines.
Null where the recording does not cover the window; „neconcludent” where n is under the stated minimum.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from app.analytics import accessibility, reliability
from app.common import gtfs, state
from app.common.errors import not_found
from app.common.timeutil import iso, parse_iso
from app.config import now
from app.live import missing as o2
from app.live import reports as rp
from app.live.check import compute_live_check
from app.m1_disruption.impact import counts_as_lost
from app.m4_access import detour
from app.m4_access.spillover import compute_spillover
from app.models.base import I18n
from app.observed import store

MIN_PASSAGES = 10
MIN_REPORTS = 10
MIN_SPILL_POINTS = 100
MIN_TRIPS = 20
RADIUS_M = 500.0

WORDING = I18n(ro="Estimare din datele live, nu raportul oficial. Ce s-a măsurat în fereastra înregistrată, nu tot ce s-a întâmplat.",
               en="Estimate from the live data, not the official report.")
CAVEAT = I18n(ro=("Cifrele acoperă doar fereastra înregistrată (vineri după-amiază și weekend), nu toată perioada lucrării. "
                  "Nu atribuie vina nimănui; SMTT decide eventualele excepții."),
              en="Figures cover only the recorded window, not the whole works period.")


def _fig(id_, ro, en, planned=None, measured=None, value=None, n=None, conclusive=None, window=None, source="",
         detail=None) -> dict:
    return {"id": id_, "label": {"ro": ro, "en": en}, "planned": planned, "measured": measured, "value": value, "n": n,
            "conclusive": conclusive, "window": window, "source": source, "detail": detail}


def _window_label(a: datetime, b: datetime) -> dict:
    ro, en = store.label(a, b)
    return {"ro": ro, "en": en}


def _stops(closure: dict, analysis: dict | None, win: dict | None) -> dict:
    planned_n = sum(1 for s in (analysis or {}).get("stops") or [] if counts_as_lost(s))
    planned = f"{planned_n} stații-linie suspendate în anunț (GTFS SMTT + anunț STPT)"
    try:
        lc = compute_live_check(closure["id"])
    except Exception:
        lc = None
    s = (lc or {}).get("summary") or {}
    sk, sv = s.get("stopsSkipped"), s.get("stopsServedAnyway")
    if lc is None or lc.get("source") is None or sk is None or sv is None:
        return _fig("stops", "Stații suspendate: planificat față de măsurat", "Suspended stops: planned vs measured",
                    planned=planned, window=win, source="verificarea în date live (app.live.check): fără înregistrare pentru fereastră")
    n = sk + sv
    share = round(sk / n, 3) if n else None
    return _fig("stops", "Stații suspendate: planificat față de măsurat", "Suspended stops: planned vs measured", planned,
                f"{sk} treceri au sărit stația, {sv} au oprit totuși, {s.get('stopsUnknown') or 0} necunoscute (din {n} judecate)",
                share, n, bool(n >= MIN_PASSAGES), win, "verificarea în date live (app.live.check)",
                {"skipped": sk, "servedAnyway": sv, "unknown": s.get("stopsUnknown"), "vehiclesSeen": s.get("vehiclesSeen")})


def _spillover(closure: dict, win: dict | None) -> dict:
    label = ("Ocolire: întârziere pe străzile ocolirii față de restul rețelei", "Detour streets vs the rest of the network")
    load = detour.cached_for(closure["id"])
    if load is None:
        return _fig("spillover", *label, planned="străzi din lista de ocolire (M4)", window=win,
                    source="M4 sarcina de ocolire + spillover: încă necalculat (în lucru)")
    sp, n = compute_spillover(closure, detour.edge_lines(load))
    if sp is None:
        return _fig("spillover", *label, planned="străzi din lista de ocolire (M4)", n=(n or {}).get("onEdges"), window=win,
                    source="M4 spillover din înregistrare: fereastra lucrării nu e în înregistrare sau lipsesc puncte")
    on = (n or {}).get("onEdges", 0)
    diff = round(sp.meanDelaySecOnEdges - sp.meanDelaySecNetwork, 1)
    return _fig("spillover", *label, "străzi din lista de ocolire (M4)",
                f"întârziere medie {sp.meanDelaySecOnEdges:.0f} s pe străzile ocolirii, {sp.meanDelaySecNetwork:.0f} s în rest",
                diff, on, bool(on >= MIN_SPILL_POINTS), win, "M4 spillover (delaySec din înregistrare)",
                {"meanDelaySecOnEdges": sp.meanDelaySecOnEdges, "meanDelaySecNetwork": sp.meanDelaySecNetwork,
                 "onEdges": on, "network": (n or {}).get("network")})


def _sesizari(closure: dict, analysis: dict | None) -> dict:
    label = ("Sesizări în fereastră față de cele 7 zile dinainte", "Reports during the window vs the 7 days before")
    cov = rp.coverage()
    area = rp.closure_area(closure, analysis)
    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    if cov is None or area is None:
        return _fig("sesizari", *label, source="sesizări, înregistrarea noastră (app.live.reports); fără acoperire")
    zone = area.buffer(RADIUS_M)
    inside = [r for r in rp.load_reports().values() if zone.contains(__import__("shapely.geometry", fromlist=["Point"]).Point(r.x, r.y))]

    def span(a, b):
        lo, hi = max(a, cov[0]), min(b, cov[1])
        return (lo, hi) if lo < hi else None

    during, before = span(start, min(end, now() if now() > start else end)), span(start - timedelta(days=rp.DAYS_BEFORE), start)
    win = _window_label(*cov)

    def rate(sp):
        if sp is None:
            return None, 0.0, 0
        n = sum(1 for r in inside if sp[0] <= r.created < sp[1])
        days = (sp[1] - sp[0]).total_seconds() / 86400
        return n / days, days, n

    rd, dd, nd = rate(during)
    rb, db, nb = rate(before)
    if rd is None or rb is None:
        return _fig("sesizari", *label, planned="7 zile înainte de lucrare", window=win,
                    source="sesizări, înregistrarea noastră (app.live.reports); fără acoperire pentru una din perioade",
                    detail={"duringReports": nd if rd is not None else None, "beforeReports": nb if rb is not None else None})
    return _fig("sesizari", *label, f"{nb} sesizări în {db:.1f} zile dinainte ({rb:.1f}/zi)",
                f"{nd} sesizări în {dd:.1f} zile din fereastră ({rd:.1f}/zi)", round(rd - rb, 2), nd + nb,
                bool(nd >= MIN_REPORTS and nb >= MIN_REPORTS), win,
                "sesizări, înregistrarea noastră (app.live.reports): doar numere, la cel mult 500 m",
                {"duringReports": nd, "duringDays": round(dd, 1), "beforeReports": nb, "beforeDays": round(db, 1)})


def _o2(closure: dict, routes: set[str], rec: tuple[datetime, datetime] | None) -> dict:
    label = ("Curse fără vehicul în datele live, pe liniile afectate", "Trips with no vehicle in the live data, on affected lines")
    if rec is None or not routes:
        return _fig("o2", *label, source="O2 (app.live.missing): fereastra lucrării nu e în înregistrare")
    start, end = rec
    f = gtfs.feed(start)
    trips, _hw = o2.scheduled_trips(f, start, end)
    trips = trips[trips["route_id"].isin(routes)]
    snaps, _files = o2.recorded(start, end)
    win = _window_label(start, end)
    if trips.empty:
        return _fig("o2", *label, planned="nicio cursă planificată în fereastra înregistrată", n=0, window=win,
                    source="O2 (app.live.missing)")
    res = o2.classify_trips(trips.reset_index(drop=True), snaps, start.timestamp(), end.timestamp())
    ob, mi = res.count("observed"), res.count("missed")
    n = ob + mi
    return _fig("o2", *label, f"{n} curse planificate și judecate pe {len(routes)} linii",
                f"{mi} fără vehicul în datele live (nu „neefectuate”), {ob} observate", round(mi / n, 3) if n else None, n,
                bool(n >= MIN_TRIPS), win, "O2 (app.live.missing)", {"observed": ob, "missed": mi, "unknown": res.count("unknown")})


def _l3(routes: set[str]) -> dict:
    label = ("Punctualitatea liniilor afectate", "Punctuality of the affected lines")
    try:
        rep = reliability.report()
    except RuntimeError:
        return _fig("l3", *label, source="L3 (app.analytics.reliability): în lucru")
    rows = [(l["punctuality"]["n"], l["punctuality"]["onTime"] or 0) for l in rep["lines"]
            if l["routeId"] in routes and l["punctuality"]["n"]]
    win = rep["recording"]["label"]
    n = sum(a for a, _ in rows)
    if not n:
        return _fig("l3", *label, window=win, source="L3 (app.analytics.reliability): nicio oprire observată pe liniile afectate")
    share = round(sum(a * b for a, b in rows) / n, 3)
    return _fig("l3", *label, None, f"{share:.0%} dintre opririle observate la timp (−60..+300 s), pe {len(rows)} linii", share, n,
                bool(n >= reliability.MIN_EVENTS * 3), win, "L3 (app.analytics.reliability)")


def job_key(closure_id: str) -> str:
    from app.common import jobs

    return f"balance:v1:{closure_id}:{jobs.closure_fingerprint(closure_id)}:{store._stamp()}"


def balance(closure_id: str) -> dict:
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id}.")
    try:
        analysis = state.read("closures", closure_id, state.PART_ANALYSIS)
    except ValueError:
        analysis = None
    cov = store.coverage()
    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    rec = None
    if cov and max(start, cov["first"]) < min(end, cov["last"]):
        rec = (max(start, cov["first"]), min(end, cov["last"]))
    win = _window_label(*rec) if rec else None
    routes = detour.own_routes(closure)
    figs = [_stops(closure, analysis, win), _spillover(closure, win), _sesizari(closure, analysis), _o2(closure, routes, rec),
            _l3(routes) if rec else _fig("l3", "Punctualitatea liniilor afectate", "Punctuality of the affected lines",
                                         source="L3: fereastra lucrării nu e în înregistrare")]
    c = cov
    return {"closureId": closure_id, "title": closure["title"], "windowStart": iso(start), "windowEnd": iso(end),
            "windowEnded": end <= now(), "recording": accessibility.recording_info(c["first"], c["last"]) if c else
            {"from": None, "to": None, "hours": 0, "label": None}, "figures": figs, "wording": WORDING.model_dump(),
            "caveat": CAVEAT.model_dump(),
            "provenance": [p.model_dump() for p in accessibility.provenances(c["first"], c["last"], "bilanț lucrare")] if c else []}
