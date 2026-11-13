"""`make precompute`: warm the caches and store the three prepared closures as `analyzed`.

    uv run python -m app.precompute            # idempotent; keeps decisions and a published case
    uv run python -m app.precompute --reset    # back to the demo start: prepared cases analyzed,
                                               # their decisions and publish record removed

Steps (SPEC §10): city files, GTFS stop patterns and departure index, the OSM street cache the
notice parser uses, m1-core's walking graph and population grid; then for each case of
app.cases.catalog: build the closure from its real notice (app.cases.build), analyze it with
app.m1_disruption.analysis and compute its impact. A prepared case is never `published` here
(D-011): „Publică” is pressed live in the demo.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
import time
from typing import Callable

from app.config import ensure_dirs, get_settings

log = logging.getLogger("precompute")


def _step(name: str, fn: Callable[[], object]) -> object:
    t = time.perf_counter()
    try:
        out = fn()
    except Exception as e:  # report and go on: one missing source must not stop the others
        print(f"  FAIL {name}: {type(e).__name__}: {e}", flush=True)
        return None
    print(f"  ok   {name} ({time.perf_counter() - t:.1f} s)", flush=True)
    return out


def _optional(module: str, attr: str) -> Callable | None:
    """A function of another module, or None while that module does not exist yet."""
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as e:
        if e.name and module.startswith(e.name):
            return None
        raise
    return getattr(mod, attr, None)


def warm_caches() -> None:
    from app.common import city, gtfs
    from app.m1_disruption import parser

    print("caches:", flush=True)
    _step("city network, zones, parking", lambda: (city.load_network(), city.load_zones(), city.load_parking()))
    _step("GTFS feed and stop patterns", lambda: len(gtfs.stop_patterns()))
    _step("GTFS departure index", lambda: len(gtfs.departure_index()))
    _step("street register", parser.register)
    _step("OSM streets and tram tracks", parser.osm_streets)
    warm = _optional("app.m1_disruption.impact", "warm")
    if warm is not None:
        _step("walking graph and population grid (m1-core)", warm)


def reset_case(closure_id: str) -> None:
    """Remove a prepared closure with its parts and its publish record (demo restart)."""
    from app.common import state

    state.delete("closures", closure_id)
    state.delete("published", closure_id)


def prepare_cases(reset: bool = False) -> list[dict]:
    from app.cases.build import build_case
    from app.cases.catalog import CASES
    from app.common import state

    analyze = _optional("app.m1_disruption.analysis", "analyze_closure")
    compute_impact = _optional("app.m1_disruption.impact", "compute_impact")
    conflicts_for = _optional("app.m1_disruption.conflicts", "conflicts_for")
    rows = []
    print("prepared cases:", flush=True)
    for case in CASES:
        t = time.perf_counter()
        cid = case.closure_id
        if reset:
            reset_case(cid)
        old = state.read("closures", cid) or {}
        built = build_case(case)
        state.write("closures", cid, built.closure)
        info: dict = {"id": cid, "status": None, "rows": None, "unsure": None,
                      "departuresLost": None, "stopsSuspended": None, "unread": len(built.unread)}
        if old.get("status") == "published":
            print(f"  note {cid} is published (a demo ran); kept as is. Use --reset to restart the demo.")
        if analyze is None:
            print(f"  skip {cid}: app.m1_disruption.analysis is not there yet (closure stored as draft)")
        else:
            a = analyze(built.closure)
            info.update(rows=len(a.stops), unsure=a.unsureCount)
            if compute_impact is not None:
                try:
                    imp = compute_impact(cid)
                    info.update(departuresLost=imp.totals.departuresLost, stopsSuspended=imp.totals.stopsSuspended)
                except Exception as e:  # e.g. 422 OUTSIDE_FEED: the number stays unknown, never 0
                    print(f"  note {cid} impact not computed: {getattr(e, 'code', type(e).__name__)}: {e}")
        info["status"] = (state.read("closures", cid) or {}).get("status")
        info["seconds"] = round(time.perf_counter() - t, 1)
        rows.append(info)
        print("  ok   " + "  ".join(f"{k}={v}" for k, v in info.items()), flush=True)
    if conflicts_for is not None and analyze is not None:
        # after all cases exist, so each one sees the others (Mocioni x 16 Decembrie)
        for info in rows:
            try:
                found = conflicts_for(info["id"])
                info["conflicts"] = [c.otherClosureId for c in found]
                print(f"  ok   conflicts {info['id']}: {info['conflicts'] or 'none'}", flush=True)
            except Exception as e:
                print(f"  note {info['id']} conflicts not computed: {type(e).__name__}: {e}")
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Warm the caches and store the prepared closures as analyzed.")
    ap.add_argument("--reset", action="store_true",
                    help="drop the prepared closures' decisions and publish records first (demo restart)")
    ap.add_argument("--cases-only", action="store_true", help="skip the cache warm-up")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    s = get_settings()
    ensure_dirs(s)
    print(f"DATA_DIR={s.data_dir}", flush=True)
    t0 = time.perf_counter()
    if not args.cases_only:
        warm_caches()
    rows = prepare_cases(reset=args.reset)
    bad = [r["id"] for r in rows if r["status"] not in ("analyzed", "published")]
    print(f"done in {time.perf_counter() - t0:.1f} s" + (f"; not analyzed: {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
