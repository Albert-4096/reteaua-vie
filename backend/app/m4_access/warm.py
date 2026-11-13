"""`make precompute` hook (SPEC §10): access (hospital, school, rail station; 30 min) for the
prepared cases, and the M2 demo route. Results go into the job cache, so the API answers 200 at once.

Also the hero case as it will be after the clerk's live decisions (D-012: the 11067 gold
label), so the demo never waits for R5 after „Confirmă”. Nothing is written to the case.
"""

from __future__ import annotations

import copy
import json
import logging
import time
from pathlib import Path

from app.common.jobs import compute_and_cache

log = logging.getLogger("reteaua_vie.m4_access.warm")

WARM_MINUTES = 30


def warm_access(closure_ids: list[str]) -> None:
    from app.m4_access import access
    from app.m4_access.api_access import access_key

    for cid in closure_ids:
        for dest in access.DESTS:
            t = time.perf_counter()
            try:
                a = compute_and_cache(access_key(cid, dest, WARM_MINUTES),
                                      lambda cid=cid, dest=dest: access.compute_access(cid, dest, WARM_MINUTES))
            except Exception as e:  # one case must not stop the others
                print(f"  FAIL access {cid} {dest}: {type(e).__name__}: {e}", flush=True)
                continue
            print(f"  ok   access {cid} {dest} {WARM_MINUTES} min: losing {a.totals.residentsLosing} "
                  f"({time.perf_counter() - t:.1f} s)", flush=True)


def warm_route() -> None:
    try:
        from app.m2_routing import plan
    except ImportError:  # M2 not built yet
        return
    t = time.perf_counter()
    try:
        p = plan.warm_demo_route()
    except Exception as e:
        print(f"  FAIL demo route: {type(e).__name__}: {e}", flush=True)
        return
    print(f"  ok   demo route: {p.durationMinutes} min, avoids {p.avoidedStopIds} "
          f"({time.perf_counter() - t:.1f} s)", flush=True)


# --- D-012: the hero case with the clerk decisions the demo takes live -----------------------

HERO = "cl_20261108_16dec"
GOLD_LABEL = Path(__file__).resolve().parents[3] / "eval" / "labels" / "11067.json"


def gold_analysis() -> dict | None:
    """The stored hero analysis with the 11067 gold label applied as decisions (in memory only).

    Same rule as eval/run.py hero_figures: an unsure row the label lists as suspended is
    ticked, one it lists as uncertain (the ring Banatul -> Piața Maria) is unticked.
    """
    from app.common import state

    if not GOLD_LABEL.is_file() or not state.exists("closures", HERO, state.PART_ANALYSIS):
        return None
    label = json.loads(GOLD_LABEL.read_text(encoding="utf-8"))
    pos, unc = set(), set()
    for a in label["gold"]["routeActions"]:
        pos |= {(str(s), a["routeId"], a["directionId"]) for s in a["suspendedStopIds"]}
        unc |= {(str(s), a["routeId"], a["directionId"]) for s in a["uncertainStopIds"]}
    analysis = copy.deepcopy(state.read("closures", HERO, state.PART_ANALYSIS))
    for r in analysis["stops"]:
        key = (str(r["stopId"]), r["routeId"], r["directionId"])
        if r.get("state") == "unsure" and key in pos:
            r["confirmed"] = True
        elif r.get("state") == "unsure" and key in unc:
            r["confirmed"] = False
    return analysis


def warm_hero_decided() -> None:
    """Access (30 min, 3 destinations) and the demo route as they will be after the clerk decides."""
    from app.common import jobs, state
    from app.m1_disruption import impact as imp
    from app.m2_routing import plan
    from app.m4_access import access

    fingerprint_of = getattr(jobs, "fingerprint_of", None)
    analysis = gold_analysis()
    if fingerprint_of is None or analysis is None:
        print("  skip hero with the D-012 decisions: "
              + ("jobs.fingerprint_of missing" if fingerprint_of is None else "no gold label or hero case"), flush=True)
        return
    closure = state.read("closures", HERO)
    lost = {imp.row_key(r) for r in analysis["stops"] if imp.counts_as_lost(r)}
    fp = fingerprint_of(closure, analysis)
    for dest in access.DESTS:
        key = f"access:v{access.ACCESS_VERSION}:{HERO}:{dest}:{WARM_MINUTES}:{fp}"
        t = time.perf_counter()
        a = compute_and_cache(key, lambda dest=dest: access.access_for(closure, lost, dest, WARM_MINUTES))
        print(f"  ok   access {HERO} {dest} {WARM_MINUTES} min, D-012 decisions ({len(lost)} rows): "
              f"losing {a.totals.residentsLosing} ({time.perf_counter() - t:.1f} s)", flush=True)
    t = time.perf_counter()
    p = plan.warm_demo_route({HERO: analysis})
    print(f"  ok   demo route, D-012 decisions: {p.durationMinutes} min, avoids {p.avoidedStopIds} "
          f"({time.perf_counter() - t:.1f} s)", flush=True)


def warm(closure_ids: list[str]) -> None:
    warm_access(closure_ids)
    warm_route()
    if HERO in closure_ids:
        try:
            warm_hero_decided()
        except Exception as e:
            print(f"  FAIL hero with the D-012 decisions: {type(e).__name__}: {e}", flush=True)


if __name__ == "__main__":
    import sys

    warm(sys.argv[1:] or ["cl_20261108_16dec", "cl_20261107_e3", "cl_20261102_mocioni"])
