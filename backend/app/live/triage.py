"""R4: a person's decision on a „fără vehicul” / „parțial” row of O2, and what it unlocks.

A person (a role, never a name: „dispecer STPT”) confirms, rejects or marks „nu știu” a
row of GET /api/live/missing, with an optional reason. Every decision is appended to one
journal in $DATA_DIR/state/triage/decisions.json; the latest decision on the same route
and window is the one in force. The journal is the monthly log SMTT reads (log_csv).

Only a confirmed row leaves the platform: `confirmed_gaps(at)` feeds R2's „fără vehicul”
state and S1's `confirmed_gap(route_id, at)` hook. A confirmation covers its window and
continues after it while no vehicle of the line shows in a healthy snapshot (at most
CONTINUE_MAX). „Respins” and „nu știu” never reach CityApp. We never write „cursă
neefectuată”: SMTT classifies trips.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta

from app.common import state
from app.common.errors import ApiError, invalid
from app.common.timeutil import iso, parse_iso
from app.config import TZ, real_now
from app.live import missing

KIND, LOG_ID = "triage", "decisions"
CONTINUE_MAX = timedelta(hours=6)

REASONS = {
    "dispozitiv_bord": "dispozitiv de bord",
    "linie_neoperata": "linie neoperată",
    "trafic_lucrari_vreme": "trafic, lucrări sau vreme",
    "gol_date": "gol în date",
}
DECISIONS = {"confirmat": "confirmat", "respins": "respins", "nu_stiu": "nu știu"}


def journal() -> list[dict]:
    """Every decision, oldest first."""
    return list(state.read(KIND, LOG_ID) or [])


def _key(d: dict) -> tuple[str, str, str]:
    return d["routeId"], iso(parse_iso(d["window"]["start"])), iso(parse_iso(d["window"]["end"]))


def latest() -> dict[tuple[str, str, str], dict]:
    """The decision in force per (route, window start, window end): the newest one."""
    out: dict = {}
    for d in journal():
        out[_key(d)] = d
    return out


def decision_for(route_id: str, window: dict) -> dict | None:
    return latest().get(_key({"routeId": route_id, "window": window}))


def _case_for(start: datetime, end: datetime) -> str | None:
    for cid, c in missing.CASES.items():
        if parse_iso(c["start"]) == start and parse_iso(c["end"]) == end:
            return cid
    return None


def record(route_id: str, body: dict) -> dict:
    """Store one decision on a row the detector flags in that window. Returns the stored decision."""
    start, end = parse_iso(body["window"]["start"]), parse_iso(body["window"]["end"])
    if start >= end or end - start > missing.MAX_WINDOW:
        raise invalid("`window` must be start < end, at most 24 h")
    if end > real_now() + timedelta(minutes=1):
        raise invalid("`window` must be in the past: we confirm what the recording shows")
    case_id = _case_for(start, end)
    result = missing.prepared(case_id) if case_id else missing.detect(start, end)
    row = next((r for r in result["routes"] if r["routeId"] == route_id), None)
    if row is None:
        raise ApiError(409, "NOT_FLAGGED",
                       f"{route_id} is not a „fără vehicul” or „parțial” row in {iso(start)} – {iso(end)}")
    when = real_now()
    rec = {
        "routeId": route_id,
        "shortName": row["shortName"],
        "window": {"start": iso(start), "end": iso(end)},
        "caseId": case_id,
        "decision": body["decision"],
        "reason": body.get("reason"),
        "who": body["who"].strip(),
        "note": (body.get("note") or "").strip() or None,
        "decidedAt": iso(when),
        "rowState": row["state"],
        "tripsInService": row["tripsInService"],
        "tripsObserved": row["tripsObserved"],
        "since": row["since"],
    }

    def append(old):
        log = list(old or [])
        rec["id"] = f"d{len(log) + 1:05d}_{when.strftime('%Y%m%dT%H%M%S')}"
        return log + [rec]

    state.update(KIND, LOG_ID, append)
    return rec


def _still_absent(route_id: str, after: datetime, at: datetime) -> bool:
    """No vehicle of the route in a healthy snapshot of [after, at), with a healthy recording."""
    if at - after < timedelta(minutes=1):
        return True
    snaps, _ = missing.recorded(after, at)
    minutes = max(1, int(-(-(at - after).total_seconds() // 60)))
    healthy = [s for s in snaps if s.healthy]
    if len(missing._healthy_minutes(healthy, after.timestamp())) / minutes < missing.MIN_HEALTHY_SHARE:
        return False  # we cannot tell: never keep a state the data does not support
    return all(route_id not in s.routes for s in healthy)


def _note(d: dict) -> str:
    when = parse_iso(d["decidedAt"])
    reason = REASONS.get(d.get("reason") or "", "necunoscut")
    return (f"Fără vehicul pe traseu (detectat, neconfirmat de STPT): nicio apariție în datele live din "
            f"{parse_iso(d['since']).strftime('%H:%M')}; confirmat în platformă de {d['who']} la "
            f"{when.strftime('%d.%m %H:%M')}; motiv: {reason}")


def confirmed_gaps(at: datetime) -> dict[str, dict]:
    """{route_id: {since, note, decisionId, decidedAt, who, reason, window}} confirmed and in force at `at`."""
    at = at.astimezone(TZ)
    now = real_now()
    out: dict[str, dict] = {}
    for d in latest().values():
        if d["decision"] != "confirmat":
            continue
        s, e = parse_iso(d["window"]["start"]), parse_iso(d["window"]["end"])
        if at < s or at - e > CONTINUE_MAX:
            continue
        if at > e and (at > now or not _still_absent(d["routeId"], e, at)):
            continue
        prev = out.get(d["routeId"])
        if prev is None or d["decidedAt"] > prev["decidedAt"]:
            out[d["routeId"]] = {"since": d["since"], "note": _note(d), "decisionId": d["id"],
                                 "decidedAt": d["decidedAt"], "who": d["who"], "reason": d.get("reason"),
                                 "window": d["window"]}
    return out


def confirmed_gap(route_id: str, at: datetime) -> dict | None:
    """S1 hook: {"since", "note"} when a person confirmed no vehicle of the line at `at`, else None."""
    g = confirmed_gaps(at).get(route_id)
    return {"since": g["since"], "note": g["note"]} if g else None


def log_csv(month: str) -> str:
    """The month's decisions (by the month of the row's window), Excel-ready: ';', UTF-8 with BOM."""
    rows = [d for d in journal() if parse_iso(d["window"]["start"]).strftime("%Y-%m") == month]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["decis_la", "linie", "route_id", "fereastra_start", "fereastra_sfarsit", "stare_rand",
                "curse_in_orar", "curse_observate", "decizie", "motiv", "cine_rol", "nota", "caz", "sursa"])
    for d in rows:
        w.writerow([d["decidedAt"], d.get("shortName") or "", d["routeId"], d["window"]["start"], d["window"]["end"],
                    "fără vehicul în datele live" if d["rowState"] == "fara_vehicul" else "parțial",
                    d["tripsInService"], d["tripsObserved"], DECISIONS[d["decision"]],
                    REASONS.get(d.get("reason") or "", "necunoscut"), d["who"], d.get("note") or "",
                    d.get("caseId") or "",
                    "datele live ale Primăriei, înregistrate de noi; decizie în platformă"])
    return "﻿" + buf.getvalue()
