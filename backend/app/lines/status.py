"""R2: one state per line at a time, for CityApp and Timi (GET /api/lines/status).

Every state comes from a published closure's `routeActions` and `temporaryRoutes`,
the way the STPT notice states them (per direction), during the closure window:
rerouted -> „deviată”, shortened or a suspended section -> „scurtată”, a whole-line
suspended -> „suspendată”; a temporary line (4b) -> „linie temporară”, and the
suspended line it stands in for gets it in `replacedBy`. Every other GTFS route
is „normală”. A closure with no `routeActions` (drawn by hand) sets no state:
the notice did not say what happens to each line.

„Fără vehicul în datele live (neconfirmat de STPT)” (O2) goes out only after a
person confirms it in the platform (R4); there is no confirmation store yet, so
this module never emits it.

`changes(at, since)` returns only the lines whose state differs between `since`
and `at`, so CityApp can notify the people who saved a line; we keep no subscriptions.
"""

from __future__ import annotations

from datetime import datetime

from app.common import gtfs, state, stpt_posts
from app.common import provenance as prov
from app.common.timeutil import iso, parse_iso
from app.config import TZ, real_now
from app.live.missing import MODES

SEVERITY = {"normala": 0, "deviata": 1, "scurtata": 2, "suspendata": 3}
ACTION_STATE = {"rerouted": "deviata", "shortened": "scurtata", "suspended": "suspendata"}
TEMP_MODES = {"bus": "autobuz", "tram": "tramvai", "trolleybus": "troleibuz"}
LABELS = {
    "normala": {"ro": "normală", "en": "normal"},
    "deviata": {"ro": "deviată", "en": "diverted"},
    "scurtata": {"ro": "scurtată", "en": "shortened"},
    "suspendata": {"ro": "suspendată", "en": "suspended"},
    "linie_temporara": {"ro": "linie temporară", "en": "temporary line"},
    "fara_vehicul": {"ro": "fără vehicul în datele live (neconfirmat de STPT)",
                     "en": "no vehicle in the live data (not confirmed by STPT)"},
}


def _active(at: datetime) -> list[dict]:
    out = []
    for c in state.list_all("closures"):
        if c.get("status") != "published" or not c.get("window"):
            continue
        if parse_iso(c["window"]["start"]) <= at < parse_iso(c["window"]["end"]):
            out.append(c)
    return sorted(out, key=lambda c: (c["window"]["start"], c["id"]))


def _notice(c: dict) -> tuple[dict | None, object | None]:
    """The closure's STPT notice ({postId, url, title}) and its provenance, if it is a saved post."""
    url = c.get("sourceUrl")
    if not url:
        return None, None
    for p in stpt_posts.load_posts().values():
        if p.link.rstrip("/") == url.rstrip("/"):
            return {"postId": p.id, "url": p.link, "title": p.title}, p.provenance()
    return {"postId": None, "url": url, "title": None}, None


def _action_state(a: dict) -> str | None:
    if a.get("action") == "suspended" and (a.get("fromStopId") or a.get("toStopId")):
        return "scurtata"  # a suspended section: the line runs on the rest
    return ACTION_STATE.get(a.get("action"))


def _replaced_by(short: str | None, temps: list[dict]) -> list[str]:
    """Temporary lines named after the line: 4 -> 4b (not 40)."""
    if not short:
        return []
    out = []
    for t in temps:
        name = (t.get("shortName") or "").strip()
        rest = name[len(short):]
        if name.lower().startswith(short.lower()) and rest.isalpha():
            out.append(name)
    return out


def statuses(at: datetime) -> tuple[list[dict], list]:
    """(one LineStatus per GTFS route + one per temporary line, provenance) at `at`."""
    at = at.astimezone(TZ)
    f = gtfs.feed(at)
    provenance = [f.provenance.model_dump(), prov.state_provenance(real_now()).model_dump()]
    routes = {r.route_id: r for r in f.routes.itertuples(index=False)}
    affected: dict[str, dict] = {}
    temp_rows: list[dict] = []
    for c in _active(at):
        notice, notice_prov = _notice(c)
        if notice_prov is not None:
            provenance.append(notice_prov.model_dump())
        temps = c.get("temporaryRoutes") or []
        where = f"anunțul STPT {notice['postId']}" if notice and notice.get("postId") else "anunțul STPT"
        source = f"Lucrare publicată în platformă ({c['id']}), după {where} / published closure"
        per_route: dict[str, dict] = {}
        for a in c.get("routeActions") or []:
            st = _action_state(a)
            rid = a.get("routeId")
            if st is None or rid not in routes:
                continue
            row = per_route.setdefault(rid, {"state": st, "dirs": set(), "whole": False})
            if SEVERITY[st] > SEVERITY[row["state"]]:
                row["state"] = st
            if a.get("directionId") in (0, 1):
                row["dirs"].add(a["directionId"])
            else:
                row["whole"] = True
        for rid, row in per_route.items():
            prev = affected.get(rid)
            if prev is not None and SEVERITY[prev["state"]] >= SEVERITY[row["state"]]:
                continue  # an earlier closure already sets an equal or stronger state
            r = routes[rid]
            short = r.route_short_name or None
            affected[rid] = {
                "state": row["state"],
                "directionIds": None if row["whole"] or row["dirs"] == {0, 1} else sorted(row["dirs"]),
                "since": c["window"]["start"], "until": c["window"]["end"],
                "closureId": c["id"], "closureTitle": c.get("title"), "notice": notice,
                "replacedBy": _replaced_by(short, temps) if row["state"] == "suspendata" else [],
                "source": source,
            }
        for t in temps:
            temp_rows.append({
                "routeId": None, "shortName": t.get("shortName"), "mode": TEMP_MODES.get(t.get("mode")),
                "state": "linie_temporara", "label": LABELS["linie_temporara"], "directionIds": None,
                "since": c["window"]["start"], "until": c["window"]["end"],
                "closureId": c["id"], "closureTitle": c.get("title"), "notice": notice,
                "replacedBy": [], "source": source,
            })
    lines = []
    for rid, r in routes.items():
        base = {"routeId": rid, "shortName": r.route_short_name or None, "mode": MODES.get(str(r.route_type))}
        if rid in affected:
            a = affected[rid]
            lines.append({**base, "label": LABELS[a["state"]], **a})
        else:
            lines.append({**base, "state": "normala", "label": LABELS["normala"], "directionIds": None,
                          "since": None, "until": None, "closureId": None, "closureTitle": None,
                          "notice": None, "replacedBy": [],
                          "source": f"Orarul SMTT GTFS {f.version or ''}, fără lucrare publicată / timetable".strip()})
    lines.sort(key=lambda x: (SEVERITY.get(x["state"], 0) == 0, x["shortName"] or ""))
    return lines + temp_rows, provenance


def _key(row: dict) -> str:
    return row["routeId"] or f"tmp:{row['closureId']}:{row['shortName']}"


def _filter(rows: list[dict], route_id: str | None, full: list[dict]) -> list[dict]:
    """The line, plus the temporary lines that stand in for it (from the full answer at `at`)."""
    if not route_id:
        return rows
    parent = next((r for r in full if r["routeId"] == route_id), None)
    stand_ins = set(parent["replacedBy"]) if parent else set()
    return [r for r in rows if r["routeId"] == route_id or (r["routeId"] is None and r["shortName"] in stand_ins)]


def lines_status(at: datetime, route_id: str | None = None, since: datetime | None = None) -> dict:
    """LinesStatus at `at`; with `since`, only the lines whose state changed in between."""
    rows, provenance = statuses(at)
    full = rows
    if since is not None:
        before = {_key(r): r for r in statuses(since)[0]}
        changed = []
        for r in rows:
            b = before.get(_key(r))
            sig = lambda x: (x["state"], x["closureId"], tuple(x["replacedBy"]), tuple(x["directionIds"] or ()))  # noqa: E731
            if b is None or sig(b) != sig(r):
                changed.append({**r, "previousState": b["state"] if b else None})
        rows = changed
    return {"at": iso(at), "since": iso(since) if since else None, "lines": _filter(rows, route_id, full),
            "provenance": provenance}
