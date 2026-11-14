"""`make precompute`: warm the caches and store the three prepared closures at the demo start.

    uv run python -m app.precompute            # idempotent; keeps decisions and a published case
    uv run python -m app.precompute --reset    # back to the demo start: the hero analyzed with no
                                               # decisions, E3 and Mocioni published again

Steps (SPEC §10): city files, GTFS stop patterns and departure index, the OSM street cache the
notice parser uses, m1-core's walking graph and population grid; then for each case of
app.cases.catalog: build the closure from its real notice (app.cases.build), analyze it with
app.m1_disruption.analysis and compute its impact.
The hero case stays `analyzed` (D-011): „Publică” is pressed live in the demo. E3 and Mocioni
(`starts_published`) were really in force at the demo clock, so they are published here with the
decisions their notices name (every row the notice names is confirmed; an `unsure` row it does
not name is unticked), dated at the notice's post time. `main()` then validates their feed and makes
Mocioni's MP3s (budget-checked); `prepare_cases` alone never starts a thread or calls ElevenLabs.
Last, every app/<package>/warm*.py that defines `warm(closure_ids: list[str]) -> None` is called
with the prepared closure ids (module caches: access, detour, windows, …); a failing one is
reported and the rest go on. The posters and a warm-up are skipped when none of their inputs
changed since their last successful run (stored closures, code, GTFS feed, demo clock: see
warm_stamp); a published case is kept as is (not rebuilt) until --reset. --force runs everything.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import sys
import time
from pathlib import Path
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


def notice_decisions(analysis: dict) -> list[dict]:
    """The decisions a clerk takes from the notice alone: confirm every row the notice names,
    untick an `unsure` row it does not name; leave the other rows to the model."""
    out = []
    for r in analysis.get("stops") or []:
        named = "NAMED_IN_NOTICE" in (r.get("reasons") or [])
        if named or r.get("state") == "unsure":
            out.append({"stopId": r["stopId"], "routeId": r["routeId"],
                        "directionId": int(r["directionId"]), "confirmed": named})
    return out


def reconstructed_note(case):
    """„reconstituit: publicat în demo din anunțul STPT din <data>” (the platform did not publish it then)."""
    from app.common.stpt_posts import get_post
    from app.models.base import I18n

    post = get_post(case.post_id)
    day = post.date.strftime("%d.%m.%Y") if post else "?"
    return I18n(ro=f"reconstituit: publicat în demo din anunțul STPT din {day}",
                en=f"reconstructed: published in the demo from the STPT notice of {day}")


def mark_reconstructed(case) -> None:
    """Label the stored publish record of a `starts_published` case (a run after its first publish)."""
    from app.common import state

    if not state.exists("published", case.closure_id):
        return
    note = reconstructed_note(case).model_dump()
    state.update("published", case.closure_id, lambda old: {**old, "reconstructed": True, "reconstructedNote": note})


def publish_as_noticed(case) -> dict:
    """Publish a `starts_published` case as STPT did: its notice's decisions, at its post time."""
    from app.common import state
    from app.common.stpt_posts import get_post
    from app.m1_disruption.analysis import apply_decisions
    from app.m1_disruption.publish import publish

    cid = case.closure_id
    analysis = state.read("closures", cid, state.PART_ANALYSIS) or {}
    decisions = notice_decisions(analysis)
    if decisions:
        apply_decisions(cid, decisions)
    post = get_post(case.post_id)
    result = publish(cid, at=post.date if post else None, background=False,
                     reconstructed_note=reconstructed_note(case))
    return {"decisions": len(decisions), "alerts": len(result.alerts), "posters": len(result.posters),
            "publishedAt": result.publishedAt}


def finish_published(closure_id: str) -> None:
    """What publish() does in the background, done here and now: the feed validator, the MP3s."""
    get_validation = _optional("app.m1_disruption.publish", "get_validation")
    if get_validation is not None:
        try:
            v = get_validation(closure_id)
            print(f"  ok   validator {closure_id}: passed={v.passed} errors={v.errorCount} "
                  f"warnings={v.warningCount} ({v.method})", flush=True)
        except Exception as e:  # Java or the jar missing: GET .../validation retries later
            print(f"  note {closure_id} feed not validated: {type(e).__name__}: {e}", flush=True)
    make_audio(closure_id)


def make_audio(closure_id: str) -> None:
    """The MP3s of a published case (only the closures audio.AUDIO_CLOSURE_IDS names), budget-checked."""
    audio = _optional("app.m1_disruption.audio", "generate")
    if audio is None or closure_id not in (_optional("app.m1_disruption.audio", "AUDIO_CLOSURE_IDS") or ()):
        return
    try:
        s = audio(closure_id)
    except Exception as e:  # BudgetRefused or the network: the QR page falls back to Web Speech
        print(f"  note {closure_id} audio not made: {type(e).__name__}: {e}", flush=True)
        return
    if s.get("skipped"):
        print(f"  note {closure_id} audio skipped: {s['skipped']}", flush=True)
    else:
        print(f"  ok   audio {closure_id}: {len(s.get('made') or [])} made, {s.get('cached', 0)} cached, "
              f"{s.get('charsSpent', 0)} characters", flush=True)


def kept_info(closure_id: str) -> dict:
    """The precompute row of a stored closure that is not rebuilt (published), from its stored parts."""
    from app.common import state

    a = state.read("closures", closure_id, state.PART_ANALYSIS) or {}
    totals = (state.read("closures", closure_id, state.PART_IMPACT) or {}).get("totals") or {}
    return {"id": closure_id, "status": (state.read("closures", closure_id) or {}).get("status"),
            "rows": len(a.get("stops") or []), "unsure": a.get("unsureCount"),
            "departuresLost": totals.get("departuresLost"), "stopsSuspended": totals.get("stopsSuspended"),
            "unread": None}


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
        if old.get("status") == "published":
            # a published case is kept as is: closure, analysis, impact and publish record stay what
            # was published (rebuilding it would let the analysis drift from the published alerts,
            # and costs seconds on every warm run); --reset rebuilds it
            rows.append(kept_info(cid))
            if case.starts_published:
                mark_reconstructed(case)
            print("  ok   " + "  ".join(f"{k}={v}" for k, v in rows[-1].items())
                  + "  (published: kept as is, --reset rebuilds it)", flush=True)
            continue
        built = build_case(case)
        state.write("closures", cid, built.closure)
        info: dict = {"id": cid, "status": None, "rows": None, "unsure": None,
                      "departuresLost": None, "stopsSuspended": None, "unread": len(built.unread)}
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
        if case.starts_published and info["status"] == "analyzed":
            try:
                info.update(publish_as_noticed(case))
            except Exception as e:  # e.g. 409 UNCONFIRMED: reported; the case stays analyzed
                print(f"  FAIL {cid} not published: {getattr(e, 'code', type(e).__name__)}: {e}")
            info["status"] = (state.read("closures", cid) or {}).get("status")
        elif case.starts_published and info["status"] == "published":
            mark_reconstructed(case)
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


def warm_posters(rows: list[dict]) -> None:
    """Render the A4 poster of every stop counted as lost (m1-outputs caches the PDF by content)."""
    poster_pdf = _optional("app.m1_disruption.poster", "poster_pdf")
    counts_as_lost = _optional("app.m1_disruption.impact", "counts_as_lost")
    if poster_pdf is None or counts_as_lost is None:
        print("posters: skipped (m1-outputs poster module not there yet)")
        return
    from app.common import state

    print("posters:", flush=True)
    for info in rows:
        analysis = state.read("closures", info["id"], state.PART_ANALYSIS) or {}
        stop_ids = sorted({r["stopId"] for r in analysis.get("stops") or [] if counts_as_lost(r)})
        t, failed = time.perf_counter(), 0
        for sid in stop_ids:
            try:
                poster_pdf(info["id"], sid)
            except Exception as e:  # one bad stop must not stop the others
                failed += 1
                if failed == 1:
                    print(f"  note {info['id']} stop {sid}: {type(e).__name__}: {e}")
        print(f"  ok   {info['id']}: {len(stop_ids) - failed}/{len(stop_ids)} posters "
              f"({time.perf_counter() - t:.1f} s)", flush=True)


def warm_modules() -> list[str]:
    """Names of every app/<package>/warm*.py module, sorted."""
    import pkgutil
    from pathlib import Path

    app_dir = Path(__file__).resolve().parent
    names = []
    for pkg in sorted(p for p in app_dir.iterdir() if (p / "__init__.py").is_file()):
        for mod in pkgutil.iter_modules([str(pkg)]):
            if not mod.ispkg and mod.name.startswith("warm"):
                names.append(f"app.{pkg.name}.{mod.name}")
    return names


# --- skip what nothing changed for (R2: a warm run < 20 s) ------------------------------------
#
# The posters and every module warm-up depend only on the stored closures (input, decisions,
# status, publish record), the app's code and templates, the GTFS feed in force and the demo clock.
# After a step succeeds, its stamp of those inputs is written to $DATA_DIR/cache/precompute/; the
# next run skips the step while the stamp is the same. --force runs everything.
# The live warm-up always runs: the vehicle recording grows every 15 s.
ALWAYS_RUN = {"app.live.warm"}


def warm_stamp() -> str:
    from app.common import gtfs, state
    from app.common.jobs import closure_fingerprint
    from app.config import now

    h = hashlib.sha256()
    for c in sorted(state.list_all("closures"), key=lambda c: c["id"]):
        pub = state.read("published", c["id"])
        h.update(json.dumps([c["id"], c.get("status"), closure_fingerprint(c["id"]), pub],
                            sort_keys=True, default=str).encode())
    app_dir = Path(__file__).resolve().parent
    for f in sorted(app_dir.rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts:
            h.update(f.relative_to(app_dir).as_posix().encode())
            h.update(f.read_bytes())
    feed = gtfs.feed()
    h.update(json.dumps([feed.version, feed.sha256, now().isoformat()]).encode())
    return h.hexdigest()


def _marker(step: str) -> Path:
    return get_settings().cache_dir / "precompute" / f"{step}.json"


def unchanged(step: str, stamp: str | None) -> bool:
    try:
        return stamp is not None and json.loads(_marker(step).read_text(encoding="utf-8"))["stamp"] == stamp
    except (OSError, ValueError, KeyError):
        return False


def mark_done(step: str, stamp: str | None) -> None:
    if stamp is None:
        return
    p = _marker(step)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"stamp": stamp, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}), encoding="utf-8")


def run_warms(closure_ids: list[str], stamp: str | None = None) -> dict[str, str]:
    """Call `warm(closure_ids)` of every module warm; a failing one is logged, never fatal.

    With a `stamp` (see warm_stamp), a module whose last successful run had the same stamp is skipped.
    """
    print("module warm-ups:", flush=True)
    out: dict[str, str] = {}
    for name in warm_modules():
        t = time.perf_counter()
        if name not in ALWAYS_RUN and unchanged(name, stamp):
            print(f"  skip {name}: nothing changed since its last run", flush=True)
            out[name] = "unchanged"
            continue
        try:
            fn = getattr(importlib.import_module(name), "warm", None)
            if fn is None:
                print(f"  skip {name}: no warm(closure_ids)", flush=True)
                out[name] = "skip"
                continue
            fn(list(closure_ids))
        except Exception as e:  # one module must not stop the others
            log.exception("warm %s failed", name)
            print(f"  FAIL {name}: {type(e).__name__}: {e}", flush=True)
            out[name] = "fail"
            continue
        print(f"  ok   {name} ({time.perf_counter() - t:.1f} s)", flush=True)
        out[name] = "ok"
        mark_done(name, stamp)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Warm the caches and store the prepared closures at the demo start.")
    ap.add_argument("--reset", action="store_true",
                    help="drop the prepared closures' decisions and publish records first (demo restart)")
    ap.add_argument("--cases-only", action="store_true", help="skip the cache warm-up")
    ap.add_argument("--no-posters", action="store_true", help="skip rendering the posters")
    ap.add_argument("--no-warm", action="store_true", help="skip the module warm-ups (app/<pkg>/warm*.py)")
    ap.add_argument("--force", action="store_true",
                    help="run the posters and every warm-up even when nothing changed since their last run")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    s = get_settings()
    ensure_dirs(s)
    print(f"DATA_DIR={s.data_dir}", flush=True)
    t0 = time.perf_counter()
    if not args.cases_only:
        warm_caches()
    rows = prepare_cases(reset=args.reset)
    from app.cases.catalog import CASES_BY_CLOSURE

    for r in rows:
        if CASES_BY_CLOSURE[r["id"]].starts_published and r["status"] == "published":
            finish_published(r["id"])
    if args.force:
        import shutil

        shutil.rmtree(_marker("x").parent, ignore_errors=True)
    stamp = warm_stamp()
    if not args.no_posters:
        if unchanged("posters", stamp):
            print("posters: nothing changed since their last run (--force renders them)", flush=True)
        else:
            warm_posters(rows)
            mark_done("posters", stamp)
    if not args.no_warm:
        run_warms([r["id"] for r in rows], stamp)
    from app.common import state

    for r in rows:  # a warm-up must never publish a prepared case (D-011)
        status = (state.read("closures", r["id"]) or {}).get("status")
        if r["status"] == "analyzed" and status != "analyzed":
            print(f"  FAIL {r['id']} is {status} after the warm-ups; run --reset", flush=True)
            r["status"] = status
    bad = [r["id"] for r in rows if r["status"] not in ("analyzed", "published")]
    # E3 and Mocioni must be published at the demo start, or step 0 is empty
    bad += [r["id"] for r in rows if CASES_BY_CLOSURE[r["id"]].starts_published and r["status"] != "published"]
    print(f"done in {time.perf_counter() - t0:.1f} s" + (f"; not at the demo start: {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
