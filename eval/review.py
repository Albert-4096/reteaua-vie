"""Human review of the eval labels (fix ticket T6): a Markdown sheet per notice, and its read-back.

    uv run --project backend python eval/review.py write [--dir DIR]   # (re)write the sheets, keeps ticks
    uv run --project backend python eval/review.py read  [--dir DIR]   # the verdicts as JSON

DIR defaults to $EVAL_REVIEW_DIR (the Makefile points it at the team's private docs, outside the
repo). One file per labelled notice, `<postId>.md`: the notice text, then per line and direction
one group per gold list (suspendate / păstrate / neclare) with the stops by id and GTFS name in
pattern order. The reviewer ticks one box per group, `ok` or `greșit`, and may write a note.

Each group carries a marker comment with a hash of its stop ids. When a label changes after the
review, the hash no longer matches and the group reads as `stale` (to be checked again).
`write` keeps the ticks and notes of every group whose hash is unchanged. This script never edits
`labelledBy` in the label files: a person does that once every group reads `ok`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LISTS = (("suspendedStopIds", "suspended", "Suspendate"), ("keptStopIds", "kept", "Păstrate"),
         ("uncertainStopIds", "uncertain", "Neclare"))
MARKER = re.compile(r"<!-- review (?P<key>\S+) h=(?P<hash>[0-9a-f]{12}) -->")
BOX = re.compile(r"^- \[(?P<mark>[ xX])\] (?P<what>ok|greșit)\s*$")
NOTE = re.compile(r"^Notă:(?P<text>.*)$")
HEAD = re.compile(r"^(Recenzent|Data):(?P<text>.*)$")


def labels(label_dir: Path = HERE / "labels") -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(label_dir.glob("*.json"))]


def group_key(post_id, action: dict, kind: str) -> str:
    return f"{post_id}:{action['routeId']}:{action['directionId']}:{kind}"


def group_hash(stop_ids: list[str]) -> str:
    return hashlib.sha256(",".join(sorted(map(str, stop_ids))).encode()).hexdigest()[:12]


def groups(label: dict) -> list[dict]:
    """Every non-empty gold list of the label, one group per (line, direction, list)."""
    out = []
    for a in label["gold"]["routeActions"]:
        order = {s: i for i, s in enumerate(a.get("patternStopIds") or [])}
        for field, kind, title in LISTS:
            ids = sorted(map(str, a.get(field) or []), key=lambda s: (order.get(s, len(order)), s))
            if ids:
                out.append({"key": group_key(label["postId"], a, kind), "hash": group_hash(ids), "kind": kind,
                            "title": title, "action": a, "stopIds": ids})
    return out


def parse_sheet(text: str) -> dict:
    """{reviewer, date, groups: {key: {hash, verdict: ok|wrong|open|both, note}}} from one sheet."""
    out: dict = {"reviewer": None, "date": None, "groups": {}}
    current = None
    for line in text.splitlines():
        m = MARKER.search(line)
        if m:
            current = {"hash": m["hash"], "ok": False, "wrong": False, "note": None}
            out["groups"][m["key"]] = current
            continue
        h = HEAD.match(line.strip())
        if h and current is None:
            out["reviewer" if h.group(1) == "Recenzent" else "date"] = h["text"].strip() or None
            continue
        if current is None:
            continue
        b = BOX.match(line.strip())
        if b:
            current["ok" if b["what"] == "ok" else "wrong"] |= b["mark"] in "xX"
            continue
        n = NOTE.match(line.strip())
        if n:
            current["note"] = n["text"].strip() or None
    for g in out["groups"].values():
        ok, wrong = g.pop("ok"), g.pop("wrong")
        g["verdict"] = "both" if ok and wrong else "ok" if ok else "wrong" if wrong else "open"
    return out


def stop_names() -> dict[str, str]:
    """GTFS stop names of the newest feed (the labels were checked against it)."""
    from gtfs_small import load_feed  # noqa: PLC0415  (eval/ is on sys.path when run as a script)

    stops = load_feed().stops
    return {str(i): str(n) for i, n in zip(stops.index, stops["stop_name"])}


def render(label: dict, names: dict[str, str], old: dict | None = None) -> str:
    """The sheet of one notice; ticks and notes of `old` are kept where the group hash is unchanged."""
    old_groups = (old or {}).get("groups") or {}
    feed = label.get("feed") or {}
    lines = [
        f"# Anunț {label['postId']}: {label['title']}",
        "",
        f"Publicat {str(label.get('postDate') or '')[:10]} · {label.get('sourceUrl') or ''} · "
        f"GTFS {feed.get('version')} (sha256 {str(feed.get('sha256') or '')[:12]})",
        f"Etichete: {label['labelledBy']}",
        "",
        f"Recenzent: {(old or {}).get('reviewer') or ''}",
        f"Data: {(old or {}).get('date') or ''}",
        "",
        "Cum verifici: citește anunțul, apoi la fiecare grup bifează UN rând: `- [x] ok` dacă stațiile din "
        "grup sunt exact ce înseamnă anunțul pentru linia și sensul acela, sau `- [x] greșit` dacă nu, și "
        "scrie după `Notă:` ce lipsește sau e în plus (id-ul stației). Nu modifica rândurile `<!-- review … -->`.",
        "",
        "## Textul anunțului",
        "",
    ]
    lines += [f"> {p}" if p.strip() else ">" for p in label["noticeText"].splitlines()]
    notes = label["gold"].get("notes") or []
    if notes:
        lines += [""] + [f"- Notă etichetare: {note}" for note in notes]
    by_action = {}
    for g in groups(label):
        by_action.setdefault((g["action"]["routeId"], g["action"]["directionId"]), []).append(g)
    for (route_id, direction), gs in by_action.items():
        a = gs[0]["action"]
        lines += ["", f"## Linia {a.get('shortName') or route_id} · sensul {direction} → {a.get('headsign') or '?'} "
                      f"· {a.get('action')}", ""]
        if a.get("stopNames"):
            lines.append("Stații numite în anunț: " + ", ".join(a["stopNames"]))
        for note in a.get("notes") or []:
            lines.append(f"- {note}")
        for g in gs:
            prev = old_groups.get(g["key"])
            keep = prev is not None and prev["hash"] == g["hash"]
            verdict = prev["verdict"] if keep else "open"
            lines += ["", f"### {g['title']} ({len(g['stopIds'])})", f"<!-- review {g['key']} h={g['hash']} -->",
                      f"- [{'x' if verdict in ('ok', 'both') else ' '}] ok",
                      f"- [{'x' if verdict in ('wrong', 'both') else ' '}] greșit",
                      f"Notă: {(prev or {}).get('note') or '' if keep else ''}", ""]
            lines += [f"{i}. `{s}` {names.get(s, '(nume necunoscut)')}" for i, s in enumerate(g["stopIds"], 1)]
    return "\n".join(lines).rstrip() + "\n"


def write(review_dir: Path) -> list[Path]:
    review_dir.mkdir(parents=True, exist_ok=True)
    names = stop_names()
    out = []
    for label in labels():
        path = review_dir / f"{label['postId']}.md"
        old = parse_sheet(path.read_text(encoding="utf-8")) if path.is_file() else None
        path.write_text(render(label, names, old), encoding="utf-8")
        out.append(path)
    return out


def read(review_dir: Path | None) -> dict | None:
    """Per notice: counts of ok / wrong / open / stale groups; None when there is no review dir."""
    if review_dir is None or not review_dir.is_dir():
        return None
    notices, total = {}, {"groups": 0, "ok": 0, "wrong": 0, "open": 0, "stale": 0}
    for label in labels():
        path = review_dir / f"{label['postId']}.md"
        sheet = parse_sheet(path.read_text(encoding="utf-8")) if path.is_file() else {"groups": {}}
        n = {"groups": 0, "ok": 0, "wrong": 0, "open": 0, "stale": 0, "wrongGroups": [],
             "reviewer": sheet.get("reviewer"), "date": sheet.get("date")}
        for g in groups(label):
            n["groups"] += 1
            s = sheet["groups"].get(g["key"])
            if s is None or s["verdict"] in ("open", "both"):
                n["open"] += 1
            elif s["hash"] != g["hash"]:
                n["stale"] += 1
            elif s["verdict"] == "ok":
                n["ok"] += 1
            else:
                n["wrong"] += 1
                n["wrongGroups"].append(g["key"])
        for k in total:
            total[k] += n[k]
        notices[str(label["postId"])] = n
    return {"notices": notices, **total,
            "complete": total["groups"] > 0 and total["ok"] + total["wrong"] == total["groups"],
            "allOk": total["groups"] > 0 and total["ok"] == total["groups"],
            "note": "Group verdicts of the human review sheet (eval/review.py). labelledBy changes only "
                    "by hand, once every group is ok."}


def default_dir() -> Path | None:
    value = os.environ.get("EVAL_REVIEW_DIR")
    return Path(value) if value else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write or read the human review sheets of the eval labels.")
    ap.add_argument("action", choices=("write", "read"))
    ap.add_argument("--dir", help="review dir (default $EVAL_REVIEW_DIR)")
    args = ap.parse_args(argv)
    review_dir = Path(args.dir) if args.dir else default_dir()
    if review_dir is None:
        print("no review dir: pass --dir or set EVAL_REVIEW_DIR", file=sys.stderr)
        return 2
    if args.action == "write":
        for p in write(review_dir):
            print(f"[review] wrote {p.name}")
    else:
        print(json.dumps(read(review_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
