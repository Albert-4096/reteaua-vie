"""`make precompute` hook (SPEC §10): access (hospital, school, rail station; 30 min) for the
prepared cases, and the M2 demo route. Results go into the job cache, so the API answers 200 at once.
"""

from __future__ import annotations

import logging
import time

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


def warm(closure_ids: list[str]) -> None:
    warm_access(closure_ids)
    warm_route()


if __name__ == "__main__":
    import sys

    warm(sys.argv[1:] or ["cl_20261108_16dec", "cl_20261107_e3", "cl_20261102_mocioni"])
