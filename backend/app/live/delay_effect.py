"""R25: the delay a diversion adds, measured, with „neconcludent”.

Per recorded trip over a stretch (from its first stop to its last):

    added   = (arrival − scheduled arrival at the last stop) − (departure − scheduled departure at the first)
    drift   = the same trip's delay growth per scheduled second on its other stop-to-stop segments,
              times the stretch's scheduled time (the line's general lateness on that trip)
    effect  = added − drift

Times are our own L0 stop events (app.observed.store, from the recording), not the city feed's
`delaySec`, whose meaning for a vehicle off its GTFS path is unknown. The estimate is the median of
the per-trip effects, with a 95 % bootstrap interval that resamples whole trips (one trip = one
block). Fewer than MIN_TRIPS trips: „prea puține curse”; an interval that includes zero:
„neconcludent”. Only a measured result may go into a published alert, and a person adds it.

Stretches of a closure are L1's (app.observed.detour_cost: the stops that changed between the
timetable before the closure and the one in force); for an R18 off-route run, the stretch is the
last stop event before the run and the first one after it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.common import provenance as prov
from app.common.errors import not_found
from app.common import state
from app.config import real_now
from app.models.base import I18n

MIN_TRIPS = 10
BOOT = 2000
SEED = 20261114
MIN_CONTROL_SEGMENTS = 3

CAVEAT_RO = (" Doar vineri după-amiază și weekend, din înregistrare; fără extrapolare la zile lucrătoare.")
CAVEAT_EN = (" Friday afternoon and the weekend only, from the recording; no extrapolation to weekdays.")

METHOD = I18n(
    ro="Pentru fiecare cursă înregistrată: întârzierea adăugată pe porțiune (sosirea la ultima stație față de orar, "
       "minus plecarea de la prima față de orar), minus întârzierea pe care aceeași cursă o adună în restul traseului "
       "pentru același timp din orar. Mediana pe curse, interval 95% prin bootstrap pe curse întregi. Sub 10 curse, "
       "sau un interval care include zero: „neconcludent”. Ore din înregistrarea noastră (L0), nu delaySec din feed."
       + CAVEAT_RO,
    en="Per recorded trip: delay added over the stretch minus the same trip's drift elsewhere for the same scheduled "
       "time. Median over trips, 95 % trip-block bootstrap. Under 10 trips, or an interval through zero: inconclusive. "
       "Hours from our recording (L0), not the feed's delaySec." + CAVEAT_EN,
)


def _minutes(sec: float) -> str:
    return f"{sec / 60:.1f}".replace(".", ",")


def _text(ro: str, en: str) -> dict:
    return {"ro": ro + CAVEAT_RO, "en": en + CAVEAT_EN}


def summarize(effects: list[float] | np.ndarray, rng: np.random.Generator | None = None) -> dict:
    """DelayEffect for per-trip effects (seconds). Under MIN_TRIPS the verdict is neconcludent."""
    x = np.asarray([v for v in effects if v is not None and np.isfinite(v)], dtype=float)
    n = int(len(x))
    if n < 2:
        med = round(float(np.median(x)), 1) if n else None
        return {"n": n, "addedSec": med, "low": None, "high": None, "verdict": "neconcludent",
                "text": _text(f"Neconcludent: sub {MIN_TRIPS} curse înregistrate (avem {n})",
                              f"Inconclusive: under {MIN_TRIPS} recorded trips (we have {n})")}
    rng = rng or np.random.default_rng(SEED)
    boots = np.median(x[rng.integers(0, n, size=(BOOT, n))], axis=1)
    med, lo, hi = float(np.median(x)), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))
    out = {"n": n, "addedSec": round(med, 1), "low": round(lo, 1), "high": round(hi, 1)}
    if n < MIN_TRIPS:
        return {**out, "verdict": "neconcludent",
                "text": _text(f"Neconcludent: sub {MIN_TRIPS} curse (avem {n}; interval 95%: "
                              f"{_minutes(lo)}–{_minutes(hi)} min)",
                              f"Inconclusive: under {MIN_TRIPS} trips (we have {n}; 95% interval "
                              f"{lo / 60:.1f} to {hi / 60:.1f} min)")}
    if lo <= 0 <= hi:
        return {**out, "verdict": "neconcludent",
                "text": _text("Neconcludent: intervalul include zero",
                              "Inconclusive: the interval includes zero")}
    head_ro = (f"Ocolirea adaugă {_minutes(med)} min pe cursă" if med > 0
               else f"Pe ocolire, cursa câștigă {_minutes(-med)} min față de orar")
    verb_en = "adds" if med > 0 else "saves"
    return {**out, "verdict": "masurat",
            "text": _text(f"{head_ro} (interval 95%: {_minutes(lo)}–{_minutes(hi)}; {n} curse)",
                          f"The diversion {verb_en} {abs(med) / 60:.1f} min per trip (95 % interval "
                          f"{lo / 60:.1f} to {hi / 60:.1f}; {n} trips)")}


def _drift_rates(seg: pd.DataFrame) -> pd.Series:
    """(trip_id, service_date) -> delay growth per scheduled second over all its segments (with sums kept)."""
    g = seg.assign(gain=seg["run_sec"] - seg["sched_run_sec"]).groupby(["trip_id", "service_date"])
    return g.agg(gain=("gain", "sum"), sched=("sched_run_sec", "sum"), k=("gain", "size"))


def _effect(added: float, planned: float, own_gain: float, own_sched: float, own_k: int,
            totals: pd.Series | None) -> float | None:
    """added − drift, where drift excludes the stretch's own segments (own_*)."""
    if totals is None:
        return None
    gain, sched, k = totals["gain"] - own_gain, totals["sched"] - own_sched, totals["k"] - own_k
    if k < MIN_CONTROL_SEGMENTS or sched <= 0:
        return None
    return float(added - gain / sched * planned)


def stretch_effects(runs: pd.DataFrame, seg: pd.DataFrame, stops: tuple[str, ...]) -> list[float]:
    """Per-trip effects for L1 measured runs over the stop sequence `stops`."""
    if not len(runs):
        return []
    rates = _drift_rates(seg[seg.trip_id.isin(runs.trip_id)]) if len(seg) else None
    pairs = set(zip(stops[:-1], stops[1:]))
    own = seg[seg.trip_id.isin(runs.trip_id)]
    own = own[[(a, b) in pairs for a, b in zip(own.from_stop_id, own.to_stop_id)]]
    own = own.assign(gain=own["run_sec"] - own["sched_run_sec"]).groupby(["trip_id", "service_date"]).agg(
        gain=("gain", "sum"), sched=("sched_run_sec", "sum"), k=("gain", "size"))
    out = []
    for r in runs.itertuples(index=False):
        key = (r.trip_id, r.service_date)
        tot = rates.loc[key] if rates is not None and key in rates.index else None
        mine = own.loc[key] if key in own.index else {"gain": 0.0, "sched": 0.0, "k": 0}
        out.append(_effect(float(r.run - r.planned), float(r.planned), float(mine["gain"]), float(mine["sched"]),
                           int(mine["k"]), tot))
    return [v for v in out if v is not None]


def closure_delay_effect(closure_id: str) -> dict:
    """ClosureDelayEffect for a stored closure (app/models/delay_effect.py)."""
    from app.observed import detour_cost as dc
    from app.observed import store
    from app.observed import timetable as tt

    closure = state.read("closures", closure_id)
    if closure is None:
        raise not_found(f"closure {closure_id} not found")
    rng = np.random.default_rng(SEED)
    cov = store.coverage()
    provenance = [prov.provenance("Rețeaua Vie L0, orarul observat / observed timetable", real_now(), None, None,
                                  cov["labelRo"] if cov else "fără ore construite / no hours built").model_dump()]
    empty = summarize([])
    before_p, after_p = dc.feeds_for(closure)
    if before_p is None or after_p is None or before_p == after_p:
        return {"closureId": closure_id, "status": "fara_orar_vechi", "minTrips": MIN_TRIPS, "total": empty,
                "stretches": [], "method": METHOD.model_dump(), "provenance": provenance}
    before, after = tt.timetable_for(before_p), tt.timetable_for(after_p)
    ev, seg = store.events(), store.segments()
    found = dc.stretches(closure, before, after, dc._recorded_days(ev))
    if not found:
        return {"closureId": closure_id, "status": "fara_schimbare", "minTrips": MIN_TRIPS, "total": empty,
                "stretches": [], "method": METHOD.model_dump(), "provenance": provenance}
    names = dc._short_names(after.sha)
    rows, pooled = [], []
    for s in found:
        effects = stretch_effects(dc.measured_runs(ev, s), seg, s.after) if len(s.after) >= 2 else []
        pooled += effects
        stop_names = dc._names(after, s.after) if s.after else []
        rows.append({"routeId": s.route_id, "shortName": names.get(s.route_id), "directionId": int(s.direction_id),
                     "kind": s.kind, "fromStop": stop_names[0] if stop_names else None,
                     "toStop": stop_names[-1] if stop_names else None, "effect": summarize(effects, rng)})
    provenance.append(prov.provenance("SMTT GTFS, orarul de dinainte și cel în vigoare / before and in force",
                                      real_now(), None, f"{before.version} → {after.version}", None).model_dump())
    return {"closureId": closure_id, "status": "ok", "minTrips": MIN_TRIPS, "total": summarize(pooled, rng),
            "stretches": rows, "method": METHOD.model_dump(), "provenance": provenance}


def run_effects(tracks: list[dict], ev: pd.DataFrame, seg: pd.DataFrame) -> dict:
    """DelayEffect for R18 off-route tracks: per trip, from the last stop event before the run to the first after."""
    from app.common.timeutil import parse_iso

    effects = []
    for t in tracks:
        x = ev[ev.trip_id == t["tripId"]]
        if not len(x):
            continue
        t0, t1 = parse_iso(t["start"]).timestamp(), parse_iso(t["end"]).timestamp()
        a = x[x.dep <= t0].sort_values("dep").tail(1)
        b = x[x.arr >= t1].sort_values("arr").head(1)
        if not len(a) or not len(b) or a.service_date.iloc[0] != b.service_date.iloc[0]:
            continue
        a, b = a.iloc[0], b.iloc[0]
        added = float((b.arr - b.sched_arr) - (a.dep - a.sched_dep))
        planned = float(b.sched_arr - a.sched_dep)
        s = seg[(seg.trip_id == t["tripId"]) & (seg.service_date == a.service_date)]
        inside = s[(s.from_index >= a.stop_index) & (s.from_index < b.stop_index)]
        totals = pd.Series({"gain": float((s.run_sec - s.sched_run_sec).sum()), "sched": float(s.sched_run_sec.sum()),
                            "k": int(len(s))}) if len(s) else None
        v = _effect(added, planned, float((inside.run_sec - inside.sched_run_sec).sum()),
                    float(inside.sched_run_sec.sum()), int(len(inside)), totals)
        if v is not None:
            effects.append(v)
    return summarize(effects)
