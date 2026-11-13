"""`make precompute` warm-up for step 2 (SPEC §10).

For each prepared closure: the window ranking (14 days, and the phasing variant)
and the „Nicio măsură” scenario. For the hero case also the two prepared scenarios
of SPEC §10, „Linia 7 la 6 minute + P&R” and „Fereastra cea mai bună + pistă
temporară” (the window = the top-ranked window), their impacts and their compare.
Results go into the job cache under the same keys the routes use.
"""

from __future__ import annotations

import logging

from app.common.jobs import compute_and_cache
from app.m4_access import scenarios as sc
from app.m4_access import windows as win
from app.models.base import I18n
from app.models.v2 import ScenarioInput

log = logging.getLogger("reteaua_vie.warm_decide")

HERO = "cl_20261108_16dec"
HERO_L7 = "sp_16dec_1_l7_pr"
HERO_BEST = "sp_16dec_2_best_bike"
PHASES = 2


def park_and_ride_for(closure_id: str):
    """A P&R option from M6 for the closure: one on a closure line, else a tram one, else the shortest walk."""
    from app.m6_parking.parking import park_and_ride_options

    opts = park_and_ride_options(closure_id)
    if not opts:
        return None
    _, analysis = win.load_closure(closure_id)
    lines = {k[1] for k in win.lost_keys(analysis["stops"])}

    def score(o):
        return (not (set(o.routeIds) & lines), not any(r.startswith("R_TV_") for r in o.routeIds),
                o.walkMeters if o.walkMeters is not None else 1e9, o.stopId)

    return sorted(opts, key=score)[0]


def prepare_hero() -> list[str]:
    """Store (or refresh) the two prepared hero scenarios. Returns their ids."""
    closure, _ = win.load_closure(HERO)
    ids = []
    pr = park_and_ride_for(HERO)
    mit = [{"kind": "frequency", "routeId": "R_TV_7", "headwayMinutes": 6}]
    if pr is not None:
        mit.append({"kind": "park_and_ride", "stopId": pr.stopId, "lotId": pr.lotId})
        sc.save(ScenarioInput(closureId=HERO, title=I18n(ro="Linia 7 la 6 minute + P&R",
                                                         en="Line 7 every 6 minutes + P&R"),
                              mitigations=mit), HERO_L7)
        ids.append(HERO_L7)
    else:
        log.warning("no P&R option for %s: scenario %s not prepared", HERO, HERO_L7)
    best = compute_and_cache(win.job_key(HERO), lambda: win.suggest(HERO)).best
    lane = closure["geometry"]
    if lane and lane.get("type") == "MultiLineString":
        lane = {"type": "LineString", "coordinates": max(lane["coordinates"], key=len)}
    mit2 = [{"kind": "window", "start": best.start, "end": best.end}]
    if lane:
        mit2.append({"kind": "bike_lane", "geometry": lane})
    sc.save(ScenarioInput(closureId=HERO, title=I18n(ro="Fereastra cea mai bună + pistă temporară",
                                                     en="Best window + temporary bike lane"),
                          mitigations=mit2), HERO_BEST)
    ids.append(HERO_BEST)
    return ids


def warm(closure_ids: list[str]) -> None:
    for cid in closure_ids:
        try:
            win.load_closure(cid)
        except Exception:
            log.warning("warm_decide: %s is not an analyzed closure", cid)
            continue
        for phases in (1, PHASES):
            try:
                compute_and_cache(win.job_key(cid, phases=phases), lambda: win.suggest(cid, phases=phases))
            except Exception:
                log.exception("warm_decide: windows %s phases=%s", cid, phases)
        scenario_ids = [sc.ensure_nothing(cid).id]
        if cid == HERO:
            try:
                scenario_ids += prepare_hero()
            except Exception:
                log.exception("warm_decide: prepared hero scenarios")
        for sid in scenario_ids:
            try:
                compute_and_cache(sc.impact_job_key(sid), lambda: sc.compute_impact(sid))
            except Exception:
                log.exception("warm_decide: scenario impact %s", sid)
        if cid == HERO and {HERO_L7, HERO_BEST} <= set(scenario_ids):
            try:
                compute_and_cache(sc.compare_job_key(HERO_L7, HERO_BEST), lambda: sc.compare(HERO_L7, HERO_BEST))
            except Exception:
                log.exception("warm_decide: compare of the prepared scenarios")
