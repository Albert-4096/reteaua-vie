"""R13: the evidence journal of a closure, the rerunnable bundle and the Excel-ready CSV.

The journal is replayed from the logs that already exist: the M1 decision log (per closure), the
publish record and the R4 decisions. For every human act the impact is recomputed with the decisions
up to that act, so the numbers shown at that moment are not a copy kept by hand: anyone can rerun
them. Each line carries the hash of the previous one (a plain sha256 chain, no database)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.common import state
from app.common.errors import not_found
from app.common.timeutil import iso, parse_iso
from app.config import now
from app.live import triage
from app.m1_disruption import impact as imp
from app.models.base import I18n

GENESIS = "0" * 64


def canon(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load(closure_id: str) -> tuple[dict, dict]:
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id}.")
    analysis = state.read("closures", closure_id, state.PART_ANALYSIS)
    if analysis is None:
        raise not_found(f"Closure {closure_id} was never analyzed.", code="NOT_ANALYZED")
    return closure, analysis


def _numbers(closure: dict, rows: list[dict]) -> dict | None:
    try:
        t = imp.build_impact(closure, rows).totals
        return {"stopsSuspended": t.stopsSuspended, "departuresLost": t.departuresLost, "routesAffected": t.routesAffected}
    except Exception:       # window outside every timetable we hold: no number, never a guess
        return None


def _key(r: dict) -> tuple:
    return (r["stopId"], r["routeId"], int(r["directionId"]))


def entries(closure_id: str) -> tuple[list[dict], dict, dict]:
    closure, analysis = load(closure_id)
    final_rows = [dict(r) for r in analysis["stops"]]
    feed = analysis.get("feedVersion")
    log = (state.read("closures", closure_id, "decisions") or {}).get("log", [])
    base = [{**r, "confirmed": None} for r in final_rows]
    index = {_key(r): r for r in base}
    raw: list[dict] = []
    group: list[dict] = []

    def flush() -> None:
        if not group:
            return
        for d in group:
            if _key(d) in index:
                index[_key(d)]["confirmed"] = d["confirmed"]
        ticked = sum(1 for d in group if d["confirmed"])
        raw.append({"at": group[0]["at"], "kind": "decision", "role": None,
                    "summary": I18n(ro=f"Decizie pe stații: {len(group)} rânduri ({ticked} confirmate, {len(group) - ticked} debifate)",
                                    en=f"Stop decision: {len(group)} rows ({ticked} confirmed, {len(group) - ticked} unticked)").model_dump(),
                    "numbers": _numbers(closure, [dict(r) for r in base])})
        group.clear()

    for d in log:
        if group and d["at"] != group[0]["at"]:
            flush()
        group.append(d)
    flush()
    pub = state.read("published", closure_id)
    if pub and pub.get("publishedAt"):
        raw.append({"at": pub["publishedAt"], "kind": "publish", "role": None,
                    "summary": I18n(ro="Publicare: alertele ies în feed (GTFS-RT, DATEX II, NGSI-LD)",
                                    en="Publish: the alerts go out in the feeds (GTFS-RT, DATEX II, NGSI-LD)").model_dump(),
                    "numbers": _numbers(closure, final_rows)})
    w0, w1 = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    routes = set(closure.get("routeIds") or [])
    for d in triage.journal():
        if d["routeId"] in routes and parse_iso(d["window"]["start"]) < w1 and parse_iso(d["window"]["end"]) > w0:
            reason = triage.REASONS.get(d.get("reason") or "", "motiv necunoscut")
            raw.append({"at": d["decidedAt"], "kind": "triage", "role": d["who"],
                        "summary": I18n(ro=f"Linia {d.get('shortName') or d['routeId']}: {triage.DECISIONS.get(d['decision'], d['decision'])} ({reason})",
                                        en=f"Line {d.get('shortName') or d['routeId']}: {d['decision']} ({d.get('reason') or 'unknown reason'})").model_dump(),
                        "numbers": None})
    order = {"decision": 0, "publish": 1, "triage": 2}
    raw.sort(key=lambda e: (parse_iso(e["at"]), order[e["kind"]]))
    out, prev = [], sha(closure_id)
    for n, e in enumerate(raw, 1):
        body = {"n": n, "at": iso(parse_iso(e["at"])), "kind": e["kind"], "role": e["role"], "summary": e["summary"],
                "feedVersion": feed, "numbers": e["numbers"], "prevHash": prev}
        body["hash"] = sha(canon(body))
        prev = body["hash"]
        out.append(body)
    return out, closure, analysis


def journal(closure_id: str) -> dict:
    ents, closure, analysis = entries(closure_id)
    return {"closureId": closure_id, "entries": ents, "head": ents[-1]["hash"] if ents else None,
            "provenance": [p for p in [_prov(closure_id, len(ents), analysis.get("feedVersion"))]]}


def _prov(closure_id: str, n: int, feed: str | None) -> dict:
    from app.common import provenance as prov
    return prov.provenance(
        "Rețeaua Vie, jurnalul deciziilor / decision journal", iso(now()), None, feed,
        f"{n} acte; reconstituit din jurnalele existente (decizii pe stații, publicare, decizii R4) și recalculat: cifrele "
        "fiecărei linii sunt impactul cu deciziile până la acel moment; rolul lipsește la deciziile pe stații (nedocumentat); "
        "lanț sha256, fiecare linie poartă hash-ul celei dinainte").model_dump()


def bundle(closure_id: str, verify: bool = False) -> dict:
    ents, closure, analysis = entries(closure_id)
    rows = [{k: r.get(k) for k in ("stopId", "routeId", "directionId", "state", "confirmed", "zoneSlug", "location")}
            for r in analysis["stops"]]
    impact = imp.compute_impact(closure_id).model_dump(mode="json")
    inputs = {"closure": {k: closure.get(k) for k in ("id", "window", "routeIds", "routeActions", "temporaryRoutes", "sourceUrl")},
              "rows": rows, "feedVersion": analysis.get("feedVersion")}
    results = {"totals": impact["totals"], "byZone": impact["byZone"]}
    out = {"closureId": closure_id, "inputs": inputs, "results": results,
           "journalHead": ents[-1]["hash"] if ents else None,
           "sha256": sha(canon({"inputs": inputs, "results": results})),
           "provenance": [_prov(closure_id, len(ents), analysis.get("feedVersion"))]}
    if verify:   # rerun from the bundle's own inputs only
        again = imp.build_impact(inputs["closure"], [dict(r) for r in inputs["rows"]]).model_dump(mode="json")
        out["verified"] = canon({"totals": again["totals"], "byZone": again["byZone"]}) == canon(results)
    return out
