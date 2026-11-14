"""A8: lines that run over the same consecutive stops, and how their departures combine. GTFS only.

A shared stretch = a run of >= MIN_STOPS consecutive stops that the same set of >= 2 lines serves, in the
same travel direction (the most common trip pattern of each line and direction). At the first stop of the
stretch the departures of all those lines, per local hour of one GTFS service day, are merged:
  mean gap = the hour / departures; cv = spread of the gaps / their mean (0 = evenly spaced);
  „alternează" cv < 0.4, „mixt" up to 0.8, „în pluton" above; closeGaps = gaps of at most 2 min.
A proposal moves whole lines by a few minutes (|shift| <= MAX_SHIFT_MIN), the same departures and km,
and is kept only when it cuts cv clearly without lengthening the longest gap.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache

import numpy as np

from app.analytics.coverage import DAYS, reference_date
from app.common import gtfs
from app.common.errors import ApiError
from app.common.geo import haversine_m
from app.config import TZ, get_settings
from app.models.base import I18n

CACHE_VERSION = 1
MIN_STOPS = 3
CLOSE_GAP_SEC = 120
MIN_DEPARTURES = 3
MAX_SHIFT_MIN = 8
MIN_CV_GAIN = 0.2
CV_TOLERANCE = 0.03
PROPOSAL = I18n(ro="propunere de decalaj, de verificat de SMTT", en="offset proposal, to be checked by SMTT")

METHOD = I18n(
    ro=("Orarul GTFS SMTT al unei zile de serviciu. Un tronson comun = cel puțin "
        f"{MIN_STOPS} stații consecutive deservite, în același sens, de aceleași linii (tiparul cel mai frecvent al "
        "fiecărei linii și direcții). Plecările liniilor din prima stație a tronsonului se unesc pe ore locale: "
        "interval mediu = ora / plecări; abaterea = împrăștierea intervalelor raportată la medie (0 = uniform); "
        "„în pluton” = peste 0,8, „alternează” = sub 0,4. O propunere mută linii întregi cu cel mult "
        f"{MAX_SHIFT_MIN} min, cu aceleași plecări și aceiași km, și se păstrează doar dacă uniformizează clar "
        "intervalele fără să lungească pauza cea mai mare."),
    en=("The GTFS timetable of one service day. A shared stretch = at least "
        f"{MIN_STOPS} consecutive stops served in the same direction by the same lines (each line's most common "
        "trip pattern). Departures at the stretch's first stop are merged per local hour. A proposal moves whole "
        f"lines by at most {MAX_SHIFT_MIN} min, same departures and km."))
CAVEAT = I18n(
    ro=("Orar planificat, nu observat: nu spune ce se întâmplă pe drum. Propunerile de decalaj sunt de verificat "
        "de SMTT; nu sunt o decizie. Variantele rare de traseu nu sunt incluse."),
    en=("Planned timetable, not observed. Offset proposals are for SMTT to check; they are not a decision. "
        "Rare route variants are left out."))


def _stretches(min_stops: int) -> dict[tuple, dict]:
    pats = gtfs.stop_patterns()
    edge: dict[tuple[str, str], set[str]] = defaultdict(set)
    for p in pats.values():
        for a, b in zip(p.stop_ids, p.stop_ids[1:]):
            edge[(a, b)].add(p.route_id)
    found: dict[tuple, dict] = {}

    def flush(run, rs):
        if rs and len(run) >= min_stops:
            found.setdefault((tuple(sorted(rs)), tuple(run)), {"routes": tuple(sorted(rs)), "stops": tuple(run)})

    for p in pats.values():
        run: list[str] = []
        cur = None
        for a, b in zip(p.stop_ids, p.stop_ids[1:]):
            rs = frozenset(edge[(a, b)])
            if len(rs) >= 2 and rs == cur:
                run.append(b)
            else:
                flush(run, cur)
                run, cur = ([a, b], rs) if len(rs) >= 2 else ([], None)
        flush(run, cur)
    return found


def _gap_stats(times: np.ndarray) -> dict:
    t = np.sort(times)
    g = np.diff(t)
    if len(t) < MIN_DEPARTURES or not len(g):
        return {"mean": None, "min": None, "max": None, "close": 0, "cv": None}
    m = float(g.mean())
    return {"mean": m / 60, "min": float(g.min()) / 60, "max": float(g.max()) / 60,
            "close": int((g <= CLOSE_GAP_SEC).sum()), "cv": float(g.std() / m) if m > 0 else None}


def _pattern(cv: float | None) -> str | None:
    if cv is None:
        return None
    return "alternează" if cv < 0.4 else "mixt" if cv <= 0.8 else "în pluton"


def propose(by_line: dict[str, np.ndarray]) -> tuple[dict[str, int], float, float] | None:
    """Shifts (minutes per line, the first line fixed) that even out the merged gaps, or None."""
    ids = sorted(by_line, key=lambda r: (-len(by_line[r]), r))
    base = _gap_stats(np.concatenate(list(by_line.values())))
    if base["cv"] is None:
        return None
    shifts = {r: 0 for r in ids}
    best = base["cv"]
    for _ in range(2):
        for r in ids[1:]:
            cvs = {}
            for s in range(-MAX_SHIFT_MIN, MAX_SHIFT_MIN + 1):
                st = _gap_stats(np.concatenate([by_line[x] + {**shifts, r: s}[x] * 60 for x in ids]))
                if st["cv"] is not None:
                    cvs[s] = st["cv"]
            if cvs and min(cvs.values()) < best - 1e-9:
                # the smallest move among the near-best ones, so the same fix is not +7 in one hour and -6 in the next
                lo = min(cvs.values())
                s = min((k for k, v in cvs.items() if v <= lo + CV_TOLERANCE), key=lambda k: (abs(k), k))
                shifts = {**shifts, r: s}
                best = cvs[s]
    after = _gap_stats(np.concatenate([by_line[x] + shifts[x] * 60 for x in ids]))
    if base["cv"] - best < MIN_CV_GAIN or after["max"] > base["max"] + 1e-9:
        return None
    return {r: s for r, s in shifts.items() if s}, round(best, 2), round(after["max"], 1)


def _cache_file(sha: str, date_iso: str, min_stops: int):
    key = hashlib.sha1(f"{CACHE_VERSION}:{sha}:{date_iso}:{min_stops}:{inspect.getsource(propose)}".encode()).hexdigest()[:12]
    return get_settings().cache_dir / "analytics" / f"corridors_{key}.json"


@lru_cache(maxsize=8)
def _compute(sha: str, date_iso: str, min_stops: int) -> list[dict]:
    p = _cache_file(sha, date_iso, min_stops)
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    out = _build(date_iso, min_stops)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def _build(date_iso: str, min_stops: int) -> list[dict]:
    f = gtfs.feed()
    day = datetime.fromisoformat(date_iso).replace(tzinfo=TZ)
    deps = gtfs.departures(day, day + timedelta(days=1))
    deps = deps[["dep_ts", "stop_id", "route_id"]]
    deps = deps.assign(stop_id=deps["stop_id"].astype(str), route_id=deps["route_id"].astype(str))
    by_stop = {s: g for s, g in deps.groupby("stop_id")}
    routes = {r.route_id: (r.route_short_name or r.route_id, {"0": "tram", "3": "bus", "11": "trolleybus"}.get(str(r.route_type), "other"))
              for r in f.routes.itertuples(index=False)}
    st = f.stops.set_index("stop_id")
    out = []
    for s in _stretches(min_stops).values():
        first = s["stops"][0]
        g = by_stop.get(first)
        if g is None:
            continue
        g = g[g["route_id"].isin(s["routes"])]
        if g.empty:
            continue
        local = (g["dep_ts"].to_numpy() - int(day.timestamp()))
        hours = []
        for h in range(24):
            m = (local >= h * 3600) & (local < (h + 1) * 3600)
            if not m.any():
                continue
            per = {r: np.sort(local[m & (g["route_id"].to_numpy() == r)] - h * 3600).astype(float) for r in s["routes"]}
            per = {r: t for r, t in per.items() if len(t)}
            st_ = _gap_stats(np.concatenate(list(per.values())))
            pr = propose(per) if len(per) >= 2 and sum(len(t) for t in per.values()) >= MIN_DEPARTURES else None
            hours.append({
                "hour": h, "departures": int(m.sum()), "perLine": {r: int(len(t)) for r, t in per.items()},
                "meanGapMin": round(st_["mean"], 1) if st_["mean"] is not None else None,
                "minGapMin": round(st_["min"], 1) if st_["min"] is not None else None,
                "maxGapMin": round(st_["max"], 1) if st_["max"] is not None else None,
                "closeGaps": st_["close"], "cv": round(st_["cv"], 2) if st_["cv"] is not None else None,
                "pattern": _pattern(st_["cv"]),
                "proposal": None if pr is None else {
                    "label": PROPOSAL.model_dump(),
                    "shifts": [{"routeId": r, "shortName": routes.get(r, (r, ""))[0], "shiftMin": v}
                               for r, v in pr[0].items()],
                    "cvAfter": pr[1], "maxGapAfterMin": pr[2]}})
        if not hours:
            continue
        xs = []
        for a in s["stops"]:
            xs.append((float(st.loc[a, "stop_lon"]), float(st.loc[a, "stop_lat"])) if a in st.index else None)
        length = sum(haversine_m(p[0], p[1], q[0], q[1]) for p, q in zip(xs, xs[1:]) if p and q)
        out.append({
            "id": f"{first}-{s['stops'][-1]}-{'+'.join(s['routes'])}",
            "lines": [{"routeId": r, "shortName": routes.get(r, (r, "other"))[0], "mode": routes.get(r, ("", "other"))[1]}
                      for r in s["routes"]],
            "stops": [{"stopId": a, "name": str(st.loc[a, "stop_name"]) if a in st.index else a} for a in s["stops"]],
            "lengthMeters": int(round(length, -1)), "hours": hours,
            "bunchedHours": sum(1 for x in hours if x["pattern"] == "în pluton"),
            "shiftableHours": sum(1 for x in hours if x["proposal"])})
    out.sort(key=lambda c: (-c["bunchedHours"], -c["shiftableHours"], c["id"]))
    return out


def corridors(day: str = "weekday", route_id: str | None = None, min_stops: int = MIN_STOPS,
              only_proposals: bool = False, limit: int = 50) -> dict:
    if day not in DAYS:
        raise ApiError(422, "INVALID_INPUT", f"`day` must be one of {', '.join(DAYS)}.")
    d = reference_date(day)
    f = gtfs.feed(d)
    items = _compute(f.sha256, d.isoformat(), min_stops)
    if route_id:
        items = [c for c in items if any(l["routeId"] == route_id for l in c["lines"])]
    if only_proposals:
        items = [c for c in items if c["shiftableHours"]]
    return {"day": day, "date": d.isoformat(), "minStops": min_stops, "count": len(items),
            "corridors": items[:limit], "method": METHOD.model_dump(), "caveat": CAVEAT.model_dump(),
            "provenance": [f.provenance.model_dump()]}
