"""Independent gold set: the stops SMTT itself removed from its own timetable.

The labels in eval/labels/ are AI-assisted readings of the notice text. This gold set is
not labelled by us at all: for each pair of consecutive SMTT GTFS versions it lists, per
(route, direction), the stop ids served in the older version and no longer served in the
newer one. SPEC §11: 4.29 -> 4.30 (2 Nov) carries the Mocioni diversion (notice 11060) and a
change on M11/M29/M30 (to compare with notice 11058); 4.30 -> 4.31 (5 Nov) carries the
Podul Polonă closure (notice 11062, line E3).

"Served" = on any trip of that route and direction in the version (union of patterns).
Uses only eval/gtfs_small.py, never the backend's GTFS code, so it is a cross-check.

    DATA_DIR=/path/to/data uv run --project backend python eval/gold_gtfs_diff.py [--write]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from gtfs_small import Feed, data_dir, load_feed, newest_feed_zip  # noqa: E402

# notice -> (transition, the routes it names, by short name)
NOTICE_TRANSITIONS = {
    "11060": ("4.29->4.30", ["M32", "M36", "M37", "M38", "M46", "M51"]),
    "11058": ("4.29->4.30", ["M11", "M29", "M30"]),
    "11062": ("4.30->4.31", ["E3"]),
}


def feeds_in_order(base: Path) -> list[Feed]:
    """Every history zip plus the current one, oldest feed version first."""
    paths = sorted((base / "gtfs-history").glob("*.zip")) + [newest_feed_zip(base)]
    feeds = [load_feed(p) for p in paths]
    return sorted(feeds, key=lambda f: tuple(int(x) for x in (f.version or "0").split(".")[:2]))


def served(feed: Feed) -> dict[tuple[str, int], set[str]]:
    out: dict[tuple[str, int], set[str]] = {}
    for (rid, did), g in feed.trips.groupby(["route_id", "direction_id"]):
        stops: set[str] = set()
        for pat in g.pattern.dropna():
            stops.update(pat)
        out[(rid, int(did))] = stops
    return out


def diff(old: Feed, new: Feed) -> list[dict]:
    """Per (route, direction) present in both versions: removed and added stop ids."""
    a, b = served(old), served(new)
    rows = []
    for key in sorted(set(a) | set(b)):
        removed = sorted(a.get(key, set()) - b.get(key, set()), key=_num)
        added = sorted(b.get(key, set()) - a.get(key, set()), key=_num)
        if not removed and not added:
            continue
        rid, did = key
        short = new.routes.route_short_name.get(rid) if rid in new.routes.index else old.routes.route_short_name.get(rid)
        rows.append({
            "routeId": rid, "shortName": short, "directionId": did,
            "inOld": key in a, "inNew": key in b,
            "removedStopIds": removed, "addedStopIds": added,
            "removedNames": [old.stop_name(s) for s in removed],
            "addedNames": [new.stop_name(s) for s in added],
        })
    return rows


def _num(s: str):
    return (0, int(s)) if s.isdigit() else (1, s)


def build(base: Path | None = None) -> dict:
    base = base or data_dir()
    feeds = feeds_in_order(base)
    out = {"feeds": [{"version": f.version, "file": f.path.name, "sha256": f.sha256[:12],
                      "startDate": f.start_date} for f in feeds],
           "method": "Per (route, direction): stop ids on any trip of the older SMTT GTFS version and on no "
                     "trip of the newer one. Not labelled by us: SMTT's own timetable change.",
           "transitions": {}}
    for old, new in zip(feeds, feeds[1:]):
        out["transitions"][f"{old.version}->{new.version}"] = diff(old, new)
    return out


def gold_for_notice(gold: dict, post_id: str) -> dict | None:
    """The independent gold rows for one notice: removed (stopId, routeId, directionId)."""
    spec = NOTICE_TRANSITIONS.get(str(post_id))
    if spec is None:
        return None
    transition, shorts = spec
    rows = [r for r in gold["transitions"].get(transition, []) if r["shortName"] in shorts]
    swaps = sorted({(s, r["routeId"], r["directionId"]) for r in rows
                    for s, name in zip(r["removedStopIds"], r["removedNames"]) if name in r["addedNames"]})
    return {
        "transition": transition,
        "routes": shorts,
        # removed ids whose stop name comes back under a new id on the same line: likely a
        # renumbered or moved stop, not a stop the riders lose
        "sameNameSwaps": swaps,
        "rows": sorted({(s, r["routeId"], r["directionId"]) for r in rows for s in r["removedStopIds"]}),
        "added": sorted({(s, r["routeId"], r["directionId"]) for r in rows for s in r["addedStopIds"]}),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="write eval/results/gold_gtfs_diff.json")
    args = ap.parse_args()
    gold = build()
    for t, rows in gold["transitions"].items():
        print(f"{t}: {len(rows)} route-directions changed")
        for r in rows:
            if r["removedStopIds"]:
                print(f"  {r['shortName']:>5} dir {r['directionId']}: -{','.join(r['removedStopIds'])}"
                      + (f"  +{','.join(r['addedStopIds'])}" if r["addedStopIds"] else ""))
    if args.write:
        p = HERE / "results" / "gold_gtfs_diff.json"
        p.write_text(json.dumps(gold, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {p.relative_to(HERE.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
