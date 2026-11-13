"""`make precompute` hook: the detour load (and spillover) of the prepared cases."""

from __future__ import annotations

import time

from app.common import state
from app.m4_access import detour
from app.m4_access.spillover import with_spillover


def warm(closure_ids: list[str]) -> None:
    for cid in closure_ids:
        closure = state.read("closures", cid)
        if closure is None:
            print(f"    detour-load {cid}: no such closure, skipped", flush=True)
            continue
        t = time.perf_counter()
        result = with_spillover(closure, detour.compute_for(cid))
        spill = "spillover" if result.spillover is not None else "no recording"
        print(f"    detour-load {cid}: {len(result.edges)} edges, {len(result.routesSlowedRisk)} lines at risk, "
              f"{spill} ({time.perf_counter() - t:.1f} s)", flush=True)


if __name__ == "__main__":
    from app.cases.catalog import CASES

    warm([c.closure_id for c in CASES])
