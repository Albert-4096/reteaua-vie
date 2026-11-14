"""L1 back-test: detour minutes estimated from other lines' measured speeds vs. the minutes measured (L0).

    DATA_DIR=... uv run --project backend python eval/detour_backtest.py           # write results + README block
    DATA_DIR=... uv run --project backend python eval/detour_backtest.py --check   # exit 1 if the README is stale

Cases: every closure or timetable change whose changed stretch L0 recorded, with the timetable before
the change on disk ($DATA_DIR/gtfs-history/):
- Mocioni (notice 11060, stored closure `cl_20261102_mocioni`; GTFS 4.29 → 4.30);
- Podul Polonă (notice 11062; GTFS 4.30 → 4.31; line E3 with the stops the 4.31 diff removes, SPEC §8),
- Ghiroda (notice 11058; GTFS 4.29 → 4.30; M11, M29, M30 with the stops the diff removes),
  both built here as closures that are never stored.
Held out: the estimate uses no trip of the case's own lines (app.observed.detour_cost excludes them),
so none of the measured trips it is compared with.

Writes eval/results/detour_backtest.json and the block between <!-- backtest:start --> and
<!-- backtest:end --> in eval/README.md. Every number comes from the run, never typed by hand.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))

from app.common import state  # noqa: E402
from app.observed import detour_cost as dc  # noqa: E402
from app.observed import store  # noqa: E402

RESULTS = HERE / "results" / "detour_backtest.json"
COVERAGE_OK = 0.8   # below this street coverage the estimate is mostly the area fallback
README = HERE / "README.md"
START, END = "<!-- backtest:start -->", "<!-- backtest:end -->"

POLONA = {
    "id": "", "title": {"ro": "Podul Polonă (anunț 11062)"},
    "window": {"start": "2026-11-05T00:00:00+02:00", "end": "2026-12-31T23:59:59+02:00"},
    "routeIds": ["R_AB_E3"],
    "routeActions": [{"routeId": "R_AB_E3", "directionId": 0, "suspendedStopIds": ["344", "363", "346"]},
                     {"routeId": "R_AB_E3", "directionId": 1, "suspendedStopIds": ["346", "347", "314", "315"]}],
}

# Notice 11058 (timetable changes; GTFS 4.29 → 4.30): M11, M29 and M30 stop serving „Moldovei (Ghiroda)”
# (526 / 234) and M30 „Girație Pod Bega” (665) moves; the stop ids are the ones the 4.29 → 4.30 diff drops.
GHIRODA = {
    "id": "", "title": {"ro": "Ghiroda (anunț 11058)"},
    "window": {"start": "2026-11-02T00:00:00+02:00", "end": "2026-12-31T23:59:59+02:00"},
    "routeIds": ["R_TB_M11", "R_AB_M29", "R_AB_M30"],
    "routeActions": [{"routeId": "R_TB_M11", "directionId": 1, "suspendedStopIds": ["234"]},
                     {"routeId": "R_AB_M29", "directionId": 0, "suspendedStopIds": ["526"]},
                     {"routeId": "R_AB_M29", "directionId": 1, "suspendedStopIds": ["234"]},
                     {"routeId": "R_AB_M30", "directionId": 0, "suspendedStopIds": ["526"]},
                     {"routeId": "R_AB_M30", "directionId": 1, "suspendedStopIds": ["665"]}],
}


def _est(e) -> dict | None:
    return None if e is None else e.model_dump()


def case(name: str, closure: dict) -> dict:
    r = dc.compute_detour_cost(closure)
    rows = [s for s in r.stretches if s.estimateError is not None and s.estimateError.n]
    length = [(s.coverage or 0.0, s.estimateError.n) for s in rows]
    n = sum(k for _c, k in length)
    days = sorted({h.dayType for s in rows for h in s.byHour})
    return {
        "case": name, "status": r.status, "feedBefore": r.feedBefore, "feedAfter": r.feedAfter,
        "recording": r.label.ro if r.label else None,
        "stretches": len(r.stretches), "stretchesMeasured": len(rows), "days": days,
        "streetCoverage": {"min": min((c for c, _k in length), default=None),
                           "max": max((c for c, _k in length), default=None),
                           "tripWeighted": round(sum(c * k for c, k in length) / n, 3) if n else None},
        "plannedExtra": _est(r.totals.plannedExtra), "measuredVsPlanned": _est(r.totals.measuredVsPlanned),
        "estimateError": _est(r.totals.estimateError),
        "perStretch": [{"line": s.shortName, "direction": s.directionId, "kind": s.kind,
                        "after": s.after.stopIds, "coverage": s.coverage, "estimateError": _est(s.estimateError)}
                       for s in rows],
    }


def _min(sec: float | None) -> str:
    return "—" if sec is None else f"{sec / 60:+.1f}".replace("-", "−")


def block(results: list[dict]) -> str:
    out = [START, "", "| Case | Recording | Days | Trips (n) | Street coverage | Estimate − measured, median [90 %] | "
                      "Measured − timetable | Timetable after − before |", "|---|---|---|---|---|---|---|---|"]
    for c in results:
        e, m, p, cov = c["estimateError"], c["measuredVsPlanned"], c["plannedExtra"], c["streetCoverage"]
        if not e or not e["n"]:
            out.append(f"| {c['case']} | {c['recording'] or '—'} | — | 0 | — | no measured stretch | — | — |")
            continue
        flag = "" if e["conclusive"] else " (neconcludent)"
        if (cov["tripWeighted"] or 0) < COVERAGE_OK:
            flag += "; mostly the area's median speed"
        out.append(
            f"| {c['case']} | {c['recording']} | {', '.join(c['days'])} | {e['n']}{flag} | "
            f"{cov['min']:.0%}–{cov['max']:.0%} (trip-weighted {cov['tripWeighted']:.0%}) | "
            f"{_min(e['sec'])} min [{_min(e['low'])}, {_min(e['high'])}] | {_min(m['sec'])} min (n {m['n']}) | "
            f"{_min(p['sec'])} min (n {p['n']}) |".replace("%", " %"))
    out += ["", END]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if store.coverage() is None:
        print("no observed timetable built (run `python -m app.observed.build` in backend/)", file=sys.stderr)
        return 1
    results = [case("Mocioni (11060), M32–M51", state.read("closures", "cl_20261102_mocioni")),
               case("Podul Polonă (11062), E3", POLONA),
               case("Ghiroda (11058), M11 M29 M30", GHIRODA)]
    text = README.read_text(encoding="utf-8")
    new = block(results)
    if START in text:
        text2 = text[:text.index(START)] + new + text[text.index(END) + len(END):]
    else:
        text2 = text.rstrip() + "\n\n" + new + "\n"
    if args.check:
        return 0 if text2 == text else 1
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps({"cases": results}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    README.write_text(text2, encoding="utf-8")
    print(new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
