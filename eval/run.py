"""Run the M1 pipeline on the labelled STPT notices and score it.

Writes eval/results/latest.json with:
  - stop-level precision and recall per notice and overall, on
    (stopId, routeId, directionId) rows; stops labelled "uncertain" are not scored;
  - the share of rows sent to review („neclar”, state "unsure");
  - seconds from paste to a valid alert (if the publish path exists);
  - the E3 departures-per-weekday figure (SPEC 5.2, eval/e3_departures.py).

Run with the backend environment (from repo/):
  DATA_DIR=... uv run --project backend python eval/run.py
Options:
  --parser  module:function   default: first found of app.m1_disruption.parser:{parse_notice,parse,parse_text}
  --analyzer module:function  default: first found of app.m1_disruption.analysis:{analyze,analyze_closure}
  --no-publish                skip the paste-to-alert timing
"""

from __future__ import annotations

import argparse
import atexit
import importlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "backend"))

from gtfs_small import TZ, Feed, load_feed  # noqa: E402

PARSER_CANDIDATES = [("app.m1_disruption.parser", n) for n in ("parse_notice", "parse", "parse_text")]
ANALYZER_CANDIDATES = [("app.m1_disruption.analysis", n) for n in ("analyze", "analyze_closure", "run_analysis")]


class Missing(Exception):
    pass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def plain(obj):
    """pydantic model / dataclass / dict -> plain JSON-like data with camelCase keys when available."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json", by_alias=True)
        except TypeError:
            return obj.model_dump()
    if isinstance(obj, dict):
        return {k: plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [plain(v) for v in obj]
    if hasattr(obj, "__dict__"):
        return {k: plain(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return obj


def get(d: dict | None, *names, default=None):
    """Read a field by camelCase or snake_case name."""
    if not isinstance(d, dict):
        return default
    for n in names:
        if n in d:
            return d[n]
    return default


def find_callable(spec: str | None, candidates: list[tuple[str, str]], what: str):
    tried = []
    pairs = [tuple(spec.split(":", 1))] if spec else candidates
    absent: set[str] = set()
    for mod_name, fn_name in pairs:
        if mod_name in absent:
            continue
        try:
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError as e:
            tried.append(f"{mod_name} (module not found: {e.name})")
            absent.add(mod_name)
            continue
        fn = getattr(mod, fn_name, None)
        if callable(fn):
            return fn, f"{mod_name}:{fn_name}"
        tried.append(f"{mod_name}:{fn_name} (no such function)")
    raise Missing(f"M1 {what} not found. Tried: " + "; ".join(tried))


def git_head() -> str | None:
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return None


def iso_eq(a: str | None, b: str | None) -> bool | None:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        return datetime.fromisoformat(a) == datetime.fromisoformat(b)
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# gold and predictions as (stopId, routeId, directionId) rows
# ---------------------------------------------------------------------------

def gold_rows(label: dict) -> tuple[set, set]:
    pos, ignore = set(), set()
    for a in label["gold"]["routeActions"]:
        for s in a["suspendedStopIds"]:
            pos.add((s, a["routeId"], a["directionId"]))
        for s in a["uncertainStopIds"]:
            ignore.add((s, a["routeId"], a["directionId"]))
    return pos, ignore


def rows_from_analysis(analysis: dict) -> tuple[set, set]:
    affected, unsure = set(), set()
    for r in get(analysis, "stops", default=[]) or []:
        key = (str(get(r, "stopId", "stop_id")), get(r, "routeId", "route_id"), get(r, "directionId", "direction_id"))
        state = get(r, "state")
        confirmed = get(r, "confirmed")
        if confirmed is False:
            continue
        (unsure if state == "unsure" else affected).add(key)
    return affected, unsure


def rows_from_route_actions(closure: dict, feed: Feed, day) -> set:
    """Fallback when no analysis exists: expand the parser's routeActions on the GTFS patterns."""
    rows = set()
    for a in get(closure, "routeActions", "route_actions", default=None) or []:
        rid = get(a, "routeId", "route_id")
        dirs = [get(a, "directionId", "direction_id")]
        if dirs[0] is None:
            dirs = [0, 1]
        for d in dirs:
            pat = feed.route_stops(rid, d, day)
            action = get(a, "action")
            if action == "suspended":
                f, t = get(a, "fromStopId", "from_stop_id"), get(a, "toStopId", "to_stop_id")
                if f in pat and t in pat:
                    i, j = sorted((pat.index(f), pat.index(t)))
                    ids = pat[i:j + 1]
                else:
                    ids = pat
            elif action == "shortened":
                keep = set(get(a, "keepStopIds", "keep_stop_ids", default=None) or [])
                ids = [s for s in pat if s not in keep]
            else:
                ids = get(a, "suspendedStopIds", "suspended_stop_ids", default=None) or []
            rows |= {(str(s), rid, d) for s in ids}
    return rows


def score(pred: set, pos: set, ignore: set) -> dict:
    pred = pred - ignore
    tp, fp, fn = len(pred & pos), len(pred - pos), len(pos - pred)
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "falsePositives": sorted(map(list, pred - pos))[:50],
        "missed": sorted(map(list, pos - pred))[:50],
    }


# ---------------------------------------------------------------------------
# M1 calls
# ---------------------------------------------------------------------------

def split_parse_output(raw) -> tuple[object, dict, list]:
    """Parser output -> (closure as returned, closure as plain dict, unread sentences).

    Accepts the CONTRACT shape {closure, unread} (dict or model), a (closure, unread) pair,
    or a bare closure."""
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return raw[0], plain(raw[0]) or {}, list(raw[1] or [])
    obj = raw.get("closure") if isinstance(raw, dict) else getattr(raw, "closure", None)
    out = plain(raw)
    if obj is not None or (isinstance(out, dict) and "closure" in out):
        return obj, (out or {}).get("closure") or {}, (out or {}).get("unread") or []
    return raw, out or {}, get(out, "unread", default=[]) or []


def call_analyzer(analyze, raw_closure, closure: dict) -> dict:
    """Try the parser's own object first, then the plain dict, then the pydantic Closure model."""
    attempts = [raw_closure, closure]
    try:
        from app import models  # noqa: PLC0415
        for name in ("Closure", "ClosureInput"):
            m = getattr(models, name, None)
            if m is not None:
                try:
                    attempts.append(m.model_validate(closure))
                except Exception:
                    pass
    except Exception:
        pass
    last = None
    for arg in attempts:
        if arg is None:
            continue
        try:
            return plain(analyze(arg))
        except (TypeError, AttributeError, KeyError) as e:
            last = e
    raise last or Missing("analyzer accepted no argument form")


# ---------------------------------------------------------------------------
# paste -> valid alert, through the HTTP API in an isolated state dir
# ---------------------------------------------------------------------------

def isolated_data_dir(real: Path) -> Path:
    """A temp DATA_DIR that links every entry of the real one except state/, so the
    eval never writes closures into the demo state."""
    tmp = Path(tempfile.mkdtemp(prefix="eval-data-"))
    for p in real.iterdir():
        if p.name != "state":
            (tmp / p.name).symlink_to(p)
    (tmp / "state").mkdir()
    return tmp


def time_paste_to_alert(text: str) -> dict:
    try:
        from fastapi.testclient import TestClient  # noqa: PLC0415
        from app.main import app  # noqa: PLC0415
    except Exception as e:  # pragma: no cover - depends on the backend state
        return {"seconds": None, "status": "skipped", "reason": f"backend app not importable: {e}"}
    c = TestClient(app)
    t0 = time.perf_counter()
    steps = []

    def step(name, resp):
        steps.append({"step": name, "status": resp.status_code})
        if resp.status_code >= 400:
            raise Missing(f"{name} -> HTTP {resp.status_code}")
        return resp

    try:
        parsed = step("parse", c.post("/api/closures/parse", json={"text": text})).json()
        closure = parsed.get("closure") or {}
        cid = closure.get("id")
        if not cid or c.get(f"/api/closures/{cid}").status_code != 200:
            body = {k: v for k, v in closure.items() if k not in ("id", "status", "createdAt")}
            cid = step("create", c.post("/api/closures", json=body)).json()["id"]
        analysis = step("analyze", c.post(f"/api/closures/{cid}/analyze")).json()
        decisions = [{"stopId": r["stopId"], "routeId": r["routeId"], "directionId": r["directionId"], "confirmed": True}
                     for r in analysis.get("stops", [])]
        if decisions:
            step("confirm", c.patch(f"/api/closures/{cid}/stops", json={"decisions": decisions}))
        step("publish", c.post(f"/api/closures/{cid}/publish"))
        pb = step("feed", c.get("/api/feed/alerts.pb")).content
        from google.transit import gtfs_realtime_pb2  # noqa: PLC0415
        msg = gtfs_realtime_pb2.FeedMessage()
        msg.ParseFromString(pb)
        alerts = [e for e in msg.entity if e.HasField("alert")]
        ok = (msg.header.gtfs_realtime_version.startswith("2") and alerts
              and all(a.alert.informed_entity and a.alert.header_text.translation for a in alerts))
        secs = time.perf_counter() - t0
        return {"seconds": round(secs, 3) if ok else None, "status": "valid" if ok else "invalid",
                "alerts": len(alerts), "steps": steps,
                "validity": "protobuf parses, header 2.x, every alert has informed_entity and header_text "
                            "(internal check, not the MobilityData validator)",
                "humanStep": "every analysis row confirmed as proposed (no human think time)"}
    except Missing as e:
        return {"seconds": None, "status": "not-available", "reason": str(e), "steps": steps}
    except Exception as e:
        return {"seconds": None, "status": "error", "reason": f"{type(e).__name__}: {e}", "steps": steps}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Score the M1 pipeline on the labelled STPT notices.")
    ap.add_argument("--parser")
    ap.add_argument("--analyzer")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--out", default=str(HERE / "results" / "latest.json"))
    args = ap.parse_args()

    if not os.environ.get("DATA_DIR"):
        print("DATA_DIR is not set (see eval/README.md)", file=sys.stderr)
        return 2
    real_data = Path(os.environ["DATA_DIR"])
    # No secrets in the eval: no LLM path, no ElevenLabs call at publish.
    os.environ["ENV_FILE"] = ""
    for key in ("ELEVENLABS_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        os.environ[key] = ""
    if not args.no_publish:
        # Settings are read when app is first imported: switch to the isolated dir before that.
        tmp = isolated_data_dir(real_data)
        atexit.register(shutil.rmtree, tmp, True)  # removes the links, never what they point to
        os.environ["DATA_DIR"] = str(tmp)
        os.environ.setdefault("LIVE_DIR", str(real_data / "live"))

    feed = load_feed()
    import e3_departures  # noqa: PLC0415
    e3 = e3_departures.compute(feed)

    labels = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((HERE / "labels").glob("*.json"))]
    result = {
        "generatedAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "repoCommit": git_head(),
        "feed": e3["feed"],
        "labels": {"count": len(labels), "labelledBy": sorted({lab["labelledBy"] for lab in labels})},
        "parser": None, "analyzer": None, "scoredFrom": None,
        "notices": [],
        "overall": None,
        "e3": {k: e3[k] for k in ("figure", "date", "sameOnEveryWeekdayOfTheWindow", "label", "stopIdsTotal",
                                  "headsigns", "method", "provenance")},
        "errors": [],
    }

    status = 0
    try:
        parse, result["parser"] = find_callable(args.parser, PARSER_CANDIDATES, "parser")
    except Missing as e:
        parse = None
        result["errors"].append(str(e))
        print(f"[eval] {e}", file=sys.stderr)
        status = 2
    try:
        analyze, result["analyzer"] = find_callable(args.analyzer, ANALYZER_CANDIDATES, "analysis")
    except Missing as e:
        analyze = None
        result["errors"].append(str(e) + " -> scoring the parser's routeActions instead")
        print(f"[eval] {e}", file=sys.stderr)
    result["scoredFrom"] = "analysis" if analyze else ("routeActions" if parse else None)

    tot = {"strict": [0, 0, 0], "lenient": [0, 0, 0]}
    rows_all = rows_unsure = 0
    timings = []
    for lab in labels:
        pos, ignore = gold_rows(lab)
        n = {"postId": lab["postId"], "title": lab["title"], "goldSuspended": len(pos), "goldUncertain": len(ignore)}
        if parse is None:
            result["notices"].append(n)
            continue
        try:
            t0 = time.perf_counter()
            raw = parse(lab["noticeText"])
            n["parseSeconds"] = round(time.perf_counter() - t0, 3)
            raw_closure, closure, unread = split_parse_output(raw)
            n["unread"] = len(unread)
            win = get(closure, "window", default={}) or {}
            n["windowMatch"] = {"start": iso_eq(get(win, "start"), lab["window"]["start"]),
                                "end": iso_eq(get(win, "end"), lab["window"]["end"])}
            gold_routes = {a["routeId"] for a in lab["gold"]["routeActions"]}
            pred_routes = {get(a, "routeId", "route_id") for a in (get(closure, "routeActions", "route_actions") or [])}
            n["routes"] = {"gold": sorted(gold_routes), "predicted": sorted(r for r in pred_routes if r)}
            if analyze:
                t1 = time.perf_counter()
                analysis = call_analyzer(analyze, raw_closure, closure)
                n["analysisSeconds"] = round(time.perf_counter() - t1, 3)
                affected, unsure = rows_from_analysis(analysis)
            else:
                day = datetime.fromisoformat(lab["window"]["start"]).date()
                affected, unsure = rows_from_route_actions(closure, feed, day), set()
            n["rows"] = {"affected": len(affected), "unsure": len(unsure)}
            total_rows = len(affected | unsure)
            n["neclarShare"] = round(len(unsure) / total_rows, 4) if total_rows and analyze else None
            rows_all += total_rows
            rows_unsure += len(unsure)
            n["strict"] = score(affected, pos, ignore)            # only "affected" counts as suspended
            n["lenient"] = score(affected | unsure, pos, ignore)  # "neclar" rows count too
            for k in ("strict", "lenient"):
                for i, f in enumerate(("tp", "fp", "fn")):
                    tot[k][i] += n[k][f]
            if not args.no_publish:
                t = time_paste_to_alert(lab["noticeText"])
                n["pasteToAlert"] = t
                if t.get("seconds") is not None:
                    timings.append(t["seconds"])
        except Exception as e:
            n["error"] = f"{type(e).__name__}: {e}"
            n["trace"] = traceback.format_exc(limit=3)
            status = status or 1
        result["notices"].append(n)

    def agg(k):
        tp, fp, fn = tot[k]
        return {"tp": tp, "fp": fp, "fn": fn,
                "precision": round(tp / (tp + fp), 4) if tp + fp else None,
                "recall": round(tp / (tp + fn), 4) if tp + fn else None}

    result["overall"] = {
        "strict": agg("strict") if parse else None,
        "lenient": agg("lenient") if parse else None,
        "neclarShare": round(rows_unsure / rows_all, 4) if rows_all and analyze else None,
        "pasteToAlertSeconds": {"median": sorted(timings)[len(timings) // 2], "max": max(timings),
                                "n": len(timings)} if timings else None,
        "gtfsRtValidatorPass": None,
        "notes": [
            "Rows are (stopId, routeId, directionId). Gold rows labelled uncertain are not scored.",
            "strict: only rows in state affected count as suspended; lenient: unsure („neclar”) rows count too.",
            "gtfsRtValidatorPass: the MobilityData validator is not run by the eval yet (null = unknown).",
        ],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"overall": result["overall"], "e3": {"figure": e3["figure"], "date": e3["date"]},
                      "scoredFrom": result["scoredFrom"], "errors": result["errors"]}, ensure_ascii=False, indent=2))
    print(f"[eval] wrote {out.relative_to(REPO) if out.is_relative_to(REPO) else out}")
    return status


if __name__ == "__main__":
    sys.exit(main())
