"""Run the M1 pipeline on the labelled STPT notices and score it.

Writes eval/results/latest.json with:
  - stop-level precision and recall per notice and overall, on
    (stopId, routeId, directionId) rows; stops labelled "uncertain" are not scored;
  - the share of rows sent to review („neclar”, state "unsure");
  - seconds from paste to a valid alert (if the publish path exists), and whether the
    published feed passes the MobilityData GTFS-RT validator (jar in $DATA_DIR/tools);
  - precision and recall against an independent gold set: the stops SMTT itself removed
    from its GTFS between versions (eval/gold_gtfs_diff.py, SPEC §11);
  - the E3 departures-per-weekday figure (SPEC 5.2, eval/e3_departures.py);
  - the D-012 hero figures: the hero closure with the gold clerk decisions of 11067
    applied, on a copy in a temporary state dir (the demo case is never touched).

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
import statistics
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

from gtfs_small import TZ, Feed, feed_zip, load_feed  # noqa: E402
import gold_gtfs_diff  # noqa: E402
import review  # noqa: E402

HERO_POST = "11067"
HERO_CLOSURE = "cl_20261108_16dec"
PREPARED_FOR_INDEPENDENT = {"11060": "cl_20261102_mocioni"}

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


def call_parser(parse, text: str, post_date: str | None):
    """Parse with the notice's post date as the reference day, so „de mâine” resolves
    to the day after the post (11062: posted 3 Nov -> 4 Nov), not after today."""
    ref = datetime.fromisoformat(post_date) if post_date else None
    try:
        params = inspect.signature(parse).parameters
    except (TypeError, ValueError):
        params = {}
    if ref is not None and "reference" in params:
        return parse(text, reference=ref)
    return parse(text)


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


def set_demo_now(value: str | None) -> None:
    """Move the app's clock (DEMO_NOW) and drop the cached settings."""
    if value is None:
        os.environ.pop("DEMO_NOW", None)
    else:
        os.environ["DEMO_NOW"] = value
    from app import config  # noqa: PLC0415
    config.get_settings.cache_clear()


def run_validator(c, cid: str) -> dict:
    """GET /api/closures/{id}/validation: the MobilityData validator on the published feed."""
    r = c.get(f"/api/closures/{cid}/validation")
    if r.status_code != 200:
        return {"status": r.status_code, "passed": None}
    v = r.json()
    return {"method": v.get("method"), "passed": v.get("passed") if v.get("method") == "validator" else None,
            "errorCount": v.get("errorCount"), "warningCount": v.get("warningCount"),
            "rules": [{"id": x["id"], "severity": x["severity"], "occurrences": x["occurrences"]}
                      for x in v.get("rules") or []],
            "tool": (v.get("tool") or {}).get("version"), "fallbackReason": v.get("fallbackReason")}


def time_paste_to_alert(text: str, post_date: str | None = None) -> dict:
    """Paste -> parse -> analyze -> confirm -> publish -> valid feed, with the app clock at
    the notice's post date (as if the clerk pasted it when STPT posted it)."""
    try:
        from fastapi.testclient import TestClient  # noqa: PLC0415
        from app.main import app  # noqa: PLC0415
    except Exception as e:  # pragma: no cover - depends on the backend state
        return {"seconds": None, "status": "skipped", "reason": f"backend app not importable: {e}"}
    if post_date:
        set_demo_now(post_date)
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
        validator = run_validator(c, cid)
        return {"seconds": round(secs, 3) if ok else None, "status": "valid" if ok else "invalid",
                "alerts": len(alerts), "steps": steps, "clock": post_date, "validator": validator,
                "validity": "protobuf parses, header 2.x, every alert has informed_entity and header_text "
                            "(internal check, not the MobilityData validator)",
                "humanStep": "every analysis row confirmed as proposed (no human think time)"}
    except Missing as e:
        return {"seconds": None, "status": "not-available", "reason": str(e), "steps": steps}
    except Exception as e:
        return {"seconds": None, "status": "error", "reason": f"{type(e).__name__}: {e}", "steps": steps}


# ---------------------------------------------------------------------------
# D-012 hero figures: gold clerk decisions on a copy of the hero closure
# ---------------------------------------------------------------------------

def _sha(path: Path) -> str | None:
    import hashlib  # noqa: PLC0415
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except FileNotFoundError:
        return None


def hero_figures(real_data: Path, label: dict) -> dict:
    """Apply the 11067 gold label as the clerk's decisions to a COPY of the stored hero
    closure (temporary state dir) and read its Impact: the D-012 pitch figures.

    Decisions: every unsure row whose (stop, route, direction) the label lists as suspended
    is ticked; every unsure row the label lists as uncertain (the ring Banatul -> Piața
    Maria) is unticked. Rows the platform already marks affected keep no decision."""
    from fastapi.testclient import TestClient  # noqa: PLC0415
    from app.main import app  # noqa: PLC0415

    real_dir = real_data / "state" / "closures"
    names = [f"{HERO_CLOSURE}.json", f"{HERO_CLOSURE}.analysis.json"]
    before = {n: _sha(real_dir / n) for n in names}
    if None in before.values():
        return {"status": "not-available", "reason": f"{HERO_CLOSURE} is not stored in {real_dir} (run make precompute)"}
    closure = json.loads((real_dir / names[0]).read_text(encoding="utf-8"))
    if closure.get("status") != "analyzed":
        return {"status": "not-available", "reason": f"{HERO_CLOSURE} is {closure.get('status')}, not analyzed "
                                                     "(run make precompute --reset)"}
    work = Path(os.environ["DATA_DIR"]) / "state" / "closures"
    work.mkdir(parents=True, exist_ok=True)
    for n in names:
        shutil.copyfile(real_dir / n, work / n)

    pos, unc = gold_rows(label)
    analysis = json.loads((work / names[1]).read_text(encoding="utf-8"))
    decisions, ticked, unticked, left = [], 0, 0, []
    for r in analysis.get("stops") or []:
        if r.get("state") != "unsure":
            continue
        key = (str(r["stopId"]), r["routeId"], r["directionId"])
        if key in pos:
            decisions.append({**dict(zip(("stopId", "routeId", "directionId"), key)), "confirmed": True})
            ticked += 1
        elif key in unc:
            decisions.append({**dict(zip(("stopId", "routeId", "directionId"), key)), "confirmed": False})
            unticked += 1
        else:
            left.append(list(key))
    c = TestClient(app)
    r = c.patch(f"/api/closures/{HERO_CLOSURE}/stops", json={"decisions": decisions})
    if r.status_code != 200:
        return {"status": "error", "reason": f"PATCH stops -> HTTP {r.status_code}: {r.text[:200]}"}
    r = c.get(f"/api/closures/{HERO_CLOSURE}/impact")
    if r.status_code != 200:
        return {"status": "error", "reason": f"GET impact -> HTTP {r.status_code}: {r.text[:200]}"}
    imp = r.json()
    after = {n: _sha(real_dir / n) for n in names}
    t = imp["totals"]
    return {
        "status": "ok",
        "closureId": HERO_CLOSURE,
        "window": imp["window"],
        "decisions": {"ticked": ticked, "unticked": unticked, "undecided": left,
                      "rule": "gold label 11067: tick the unsure rows labelled suspended (line 7, certain), "
                              "untick the unsure rows labelled uncertain (ring Banatul -> Piața Maria)"},
        "stopsSuspended": t.get("stopsSuspended"),
        "departuresLost": t.get("departuresLost"),
        "residentsLosingStop": t.get("residentsLosingStop"),
        "stopRoutePairsLost": t.get("stopRoutePairsLost"),
        "routesAffected": t.get("routesAffected"),
        "method": imp.get("method"),
        "provenance": imp.get("provenance"),
        "labels": {"residentsLosingStop": "model GHSL 2020, nu recensământ"},
        "demoCaseUntouched": before == after,
        "computedOn": "a copy of the stored hero closure in a temporary state dir",
    }


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
    # Settings are read when app is first imported: switch to the isolated dir before that,
    # so neither the publish timing nor the hero copy ever writes into the demo state.
    tmp = isolated_data_dir(real_data)
    atexit.register(shutil.rmtree, tmp, True)  # removes the links, never what they point to
    os.environ["DATA_DIR"] = str(tmp)
    os.environ.setdefault("LIVE_DIR", str(real_data / "live"))
    demo_now = os.environ.get("DEMO_NOW")

    feeds: dict[Path, Feed] = {}

    def feed_at(when: str | None) -> Feed:
        """The feed in force at a notice's post date (None: the app clock), loaded once per zip."""
        path = feed_zip(at=when)
        if path not in feeds:
            feeds[path] = load_feed(path)
        return feeds[path]

    gold_diff = gold_gtfs_diff.build(real_data)
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "gold_gtfs_diff.json").write_text(json.dumps(gold_diff, ensure_ascii=False, indent=1) + "\n",
                                                         encoding="utf-8")
    import e3_departures  # noqa: PLC0415
    e3 = e3_departures.compute(feed_at(e3_departures.post_date()))

    labels = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((HERE / "labels").glob("*.json"))]
    result = {
        "generatedAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "repoCommit": git_head(),
        "feed": e3["feed"],
        "labels": {"count": len(labels), "labelledBy": sorted({lab["labelledBy"] for lab in labels}),
                   # the human review sheet ($EVAL_REVIEW_DIR, eval/review.py); null when there is none
                   "humanReview": review.read(review.default_dir())},
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
    ind = {"strict": [0, 0, 0], "lenient": [0, 0, 0]}
    validations = []
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
            raw = call_parser(parse, lab["noticeText"], lab.get("postDate"))
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
                affected, unsure = rows_from_route_actions(closure, feed_at(lab.get("postDate")), day), set()
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
            ig = gold_gtfs_diff.gold_for_notice(gold_diff, lab["postId"])
            if ig is not None:
                gold_set = {tuple(r) for r in ig["rows"]}
                n["independentGold"] = {
                    "transition": ig["transition"], "routes": ig["routes"], "goldRows": len(gold_set),
                    "sameNameSwaps": [list(x) for x in ig["sameNameSwaps"]],
                    "strict": score(affected, gold_set, set()),
                    "lenient": score(affected | unsure, gold_set, set()),
                    # how the AI-assisted label itself compares with SMTT's own change
                    "aiLabelVsIndependent": score(pos, gold_set, set()),
                }
                for k in ("strict", "lenient"):
                    for i, f in enumerate(("tp", "fp", "fn")):
                        ind[k][i] += n["independentGold"][k][f]
            if not args.no_publish:
                t = time_paste_to_alert(lab["noticeText"], lab.get("postDate"))
                n["pasteToAlert"] = t
                if t.get("seconds") is not None:
                    timings.append(t["seconds"])
                v = t.get("validator") or {}
                if v.get("passed") is not None:
                    validations.append(v["passed"])
        except Exception as e:
            n["error"] = f"{type(e).__name__}: {e}"
            n["trace"] = traceback.format_exc(limit=3)
            status = status or 1
        result["notices"].append(n)

    # The prepared Mocioni case is built on the GTFS 4.29 normal pattern (SPEC 5.3), so it can be
    # scored against SMTT's own 4.29 -> 4.30 change; read-only from the demo state.
    prepared_scores = {}
    for post_id, cid in PREPARED_FOR_INDEPENDENT.items():
        p = real_data / "state" / "closures" / f"{cid}.analysis.json"
        ig = gold_gtfs_diff.gold_for_notice(gold_diff, post_id)
        if ig is None or not p.is_file():
            continue
        affected, unsure = rows_from_analysis(json.loads(p.read_text(encoding="utf-8")))
        gold_set = {tuple(r) for r in ig["rows"]}
        prepared_scores[post_id] = {"closureId": cid, "goldRows": len(gold_set),
                                    "strict": score(affected, gold_set, set()),
                                    "lenient": score(affected | unsure, gold_set, set())}

    set_demo_now(demo_now)
    hero_label = next((lab for lab in labels if str(lab["postId"]) == HERO_POST), None)
    try:
        result["hero"] = hero_figures(real_data, hero_label) if hero_label else {
            "status": "not-available", "reason": f"no label {HERO_POST}"}
    except Exception as e:
        result["hero"] = {"status": "error", "reason": f"{type(e).__name__}: {e}"}
        status = status or 1

    def agg(k, src=tot):
        tp, fp, fn = src[k]
        return {"tp": tp, "fp": fp, "fn": fn,
                "precision": round(tp / (tp + fp), 4) if tp + fp else None,
                "recall": round(tp / (tp + fn), 4) if tp + fn else None}

    result["overall"] = {
        "strict": agg("strict") if parse else None,
        "lenient": agg("lenient") if parse else None,
        "neclarShare": round(rows_unsure / rows_all, 4) if rows_all and analyze else None,
        "pasteToAlertSeconds": {"median": round(statistics.median(timings), 3), "max": max(timings),
                                "n": len(timings)} if timings else None,
        "gtfsRtValidatorPass": (all(validations) if validations else None),
        "gtfsRtValidatorRuns": len(validations),
        "independentGold": {"strict": agg("strict", ind), "lenient": agg("lenient", ind),
                            "notices": sorted(gold_gtfs_diff.NOTICE_TRANSITIONS),
                            "preparedCases": prepared_scores} if parse else None,
        "notes": [
            "Rows are (stopId, routeId, directionId). Gold rows labelled uncertain are not scored.",
            "strict: only rows in state affected count as suspended; lenient: unsure („neclar”) rows count too.",
            "gtfsRtValidatorPass: the MobilityData gtfs-realtime-validator ($DATA_DIR/tools) on the feed after "
            "each publish; null = it did not run (no publish, or the internal fallback check ran instead).",
            "independentGold: rows SMTT removed from its own GTFS between versions (eval/gold_gtfs_diff.py), "
            "not labelled by us. The pipeline reads each notice against the current feed (4.31), which already "
            "contains the 11060 and 11062 diversions.",
        ],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"overall": result["overall"], "e3": {"figure": e3["figure"], "date": e3["date"]},
                      "hero": {k: result["hero"].get(k) for k in ("status", "stopsSuspended", "departuresLost",
                                                                  "residentsLosingStop", "stopRoutePairsLost",
                                                                  "decisions", "demoCaseUntouched", "reason")},
                      "humanReview": {k: (result["labels"]["humanReview"] or {}).get(k)
                                      for k in ("groups", "ok", "wrong", "open", "stale", "complete")},
                      "scoredFrom": result["scoredFrom"], "errors": result["errors"]}, ensure_ascii=False, indent=2))
    print(f"[eval] wrote {out.relative_to(REPO) if out.is_relative_to(REPO) else out}")
    return status


if __name__ == "__main__":
    sys.exit(main())
