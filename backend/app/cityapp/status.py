"""S1: why does (or does not) a line stop here, now. Pure assembly of what already exists:
published closures and their analysis rows (decisions applied, nearest served stop included),
the GTFS timetable of the day, and one template sentence in RO and EN (no LLM)."""

from __future__ import annotations

import importlib
import logging
from datetime import datetime, timedelta

from app.cityapp.models import LineReason, LiveCheck, NextStepFree, StopLine, StopStatus
from app.common import gtfs, state
from app.common import provenance as prov
from app.common.city import load_network
from app.common.errors import not_found
from app.common.timeutil import from_unix, iso, local_midnight, parse_iso
from app.m1_disruption import impact as imp
from app.models.base import I18n, Provenance

log = logging.getLogger("reteaua_vie.cityapp")

MAX_NAMED = 6
RO_MONTHS = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august",
             "septembrie", "octombrie", "noiembrie", "decembrie"]
EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]


# --- hook for O2 ("niciun vehicul al liniei în datele live") -------------------------------


def live_gap_hook(route_id: str, at: datetime) -> dict | None:
    """Return {"since": iso, "note": str} when a PERSON-CONFIRMED no-vehicle finding exists for the
    line at `at`, else None. Nothing produces this yet: the O2 detector is not built. When O2 is
    [READY] it exposes `app.live.missing.confirmed_gap(route_id, at)` with that return shape and this
    function starts using it; until then the response says the check is „în lucru”, never a fake answer."""
    try:
        mod = importlib.import_module("app.live.missing")
    except ImportError:
        return None
    fn = getattr(mod, "confirmed_gap", None)
    return fn(route_id, at) if fn else None


def live_feed_check() -> LiveCheck:
    try:
        ready = hasattr(importlib.import_module("app.live.missing"), "confirmed_gap")
    except ImportError:
        ready = False
    if not ready:
        return LiveCheck(status="pending", note=I18n(
            ro="în lucru: verificarea „niciun vehicul al liniei în datele live” nu e încă disponibilă",
            en="in progress: the „no vehicle of the line in the live data” check is not available yet"))
    return LiveCheck(status="ok", note=I18n(ro="verificat în datele live înregistrate",
                                            en="checked against the recorded live data"))


# --- closures active at `at` -----------------------------------------------------------------


def _active_closures(at: datetime) -> list[dict]:
    out = []
    for c in state.list_all("closures"):
        if c.get("status") != "published":
            continue
        w = c.get("window") or {}
        if parse_iso(w["start"]) <= at < parse_iso(w["end"]):
            out.append(c)
    return sorted(out, key=lambda c: c["id"])


def _action(closure: dict, route_id: str, direction: int) -> str | None:
    best = None
    for a in closure.get("routeActions") or []:
        if a["routeId"] == route_id:
            if a.get("directionId") == direction:
                return a["action"]
            if a.get("directionId") is None:
                best = a["action"]
    return best


def _timetable_day(stop_id: str, at: datetime):
    """{(route, dir): next departure ts >= at or None} for the service day of `at`, None if outside the feed."""
    day0 = local_midnight(at.date())
    day1 = day0 + timedelta(days=1)
    if not gtfs.is_covered(day0, day1):
        return None
    df = gtfs.departures(day0, day1, stop_ids=[stop_id])
    out: dict[tuple[str, int], int | None] = {}
    ts_at = int(at.timestamp())
    for (r, d), g in df.groupby([df["route_id"].astype(str), df["direction_id"].astype(int)]):
        later = g["dep_ts"][g["dep_ts"] >= ts_at]
        out[(r, int(d))] = int(later.min()) if len(later) else None
    return out


# --- sentence ----------------------------------------------------------------------------------


def _date(dt: datetime, months: list[str], en: bool) -> str:
    return f"{months[dt.month - 1]} {dt.day}" if en else f"{dt.day} {months[dt.month - 1]}"


def _names(lines: list[StopLine]) -> str:
    seen: list[str] = []
    for ln in lines:
        if ln.shortName not in seen:
            seen.append(ln.shortName)
    shown = ", ".join(seen[:MAX_NAMED])
    return shown if len(seen) <= MAX_NAMED else f"{shown} (+{len(seen) - MAX_NAMED})"


def build_sentence(name: str, state_: str, lines: list[StopLine], nearest: dict | None, until: datetime | None) -> I18n:
    no = [ln for ln in lines if ln.stops == "no"]
    yes = [ln for ln in lines if ln.stops == "yes"]
    unsure = [ln for ln in lines if ln.stops == "unconfirmed"]
    if state_ == "normal":
        if unsure:
            return I18n(ro=f"La stația {name}, liniile {_names(unsure)} sunt în verificare (anunț STPT, încă neconfirmat).",
                        en=f"At {name}, lines {_names(unsure)} are being checked (STPT notice, not yet confirmed).")
        return I18n(ro=f"La stația {name} nu avem nicio schimbare publicată; liniile opresc conform orarului.",
                    en=f"At {name} we have no published change; lines stop as scheduled.")
    if state_ == "unknown":
        return I18n(ro=f"Pentru stația {name} nu avem orarul zilei; nu putem spune ce linii opresc.",
                    en=f"We have no timetable for {name} on this day, so we cannot say which lines stop.")
    ro_until = f" până la {_date(until, RO_MONTHS, False)}" if until else ""
    en_until = f" until {_date(until, EN_MONTHS, True)}" if until else ""
    many = len({ln.shortName for ln in no}) > 1
    ro = (f"La stația {name}, " + (f"liniile {_names(no)} nu opresc" if many else f"linia {_names(no)} nu oprește")
          + f"{ro_until}, din cauza lucrărilor (anunț STPT).")
    en = (f"At {name}, " + (f"lines {_names(no)} do not" if many else f"line {_names(no)} does not")
          + f" stop{en_until} because of road works (STPT notice).")
    if state_ == "partial" and yes:
        ro += f" Opresc: {_names(yes)}."
        en += f" Still stopping: {_names(yes)}."
    if nearest and nearest.get("distanceMeters") is not None:
        d = int(nearest["distanceMeters"])
        if d > 0:
            ro += f" Cea mai apropiată stație deservită: {nearest['name']}, la aproximativ {d} m pe jos."
            en += f" Nearest served stop: {nearest['name']}, about {d} m on foot."
    return I18n(ro=ro, en=en)


# --- the answer --------------------------------------------------------------------------------


def _next_step_free(stop_id: str) -> NextStepFree | None:
    """R6: the typical wait for a step-free vehicle at this stop, from the recording (never raises)."""
    try:
        from app.analytics import accessibility

        r = accessibility.stop_report(stop_id)
    except Exception:
        log.exception("nextStepFree failed for stop %s", stop_id)
        return None
    if r is None or not r["stepFreeEvents"]:
        return None
    lbl = r["recording"]["label"]
    return NextStepFree(waitMin=r["stepFreeWaitMin"], events=r["stepFreeEvents"], lines=r["nextStepFreeLines"],
                        recordingLabel=I18n(**lbl) if lbl else None, caveat=I18n(**r["caveat"]))


def stop_status(stop_id: str, at: datetime) -> StopStatus:
    net = load_network()
    stop = net.stop_by_id.get(str(stop_id))
    if stop is None:
        raise not_found(f"No stop {stop_id}.", code="NO_SUCH_STOP")
    sid = stop["id"]

    lines: dict[tuple[str, int], StopLine] = {}
    nearest: dict | None = None
    sources: list[Provenance] = []
    ends: list[datetime] = []

    def short(r: str) -> str:
        return (net.route_by_id.get(r) or {}).get("shortName", r)

    for c in _active_closures(at):
        analysis = state.read("closures", c["id"], state.PART_ANALYSIS)
        if not analysis:
            continue
        w = c["window"]
        used = False
        for row in analysis["stops"]:
            if row["stopId"] != sid:
                continue
            lost, unsure = imp.counts_as_lost(row), imp.is_undecided(row)
            if not (lost or unsure):
                continue
            key = (row["routeId"], int(row["directionId"]))
            if key in lines and lines[key].stops == "no":
                continue
            lines[key] = StopLine(
                routeId=key[0], shortName=row.get("routeShortName") or short(key[0]), directionId=key[1],
                headsign=row.get("headsign"), stops="no" if lost else "unconfirmed",
                reason=LineReason(kind="works", closureId=c["id"], title=c["title"],
                                  action=_action(c, key[0], key[1]), since=w["start"], until=w["end"],
                                  noticeUrl=c.get("sourceUrl")),
                nextDepartureAt=None)
            ns = row.get("nearestServed")
            if lost and ns and (nearest is None or (ns.get("distanceMeters") or 0) < (nearest.get("distanceMeters") or 0)):
                nearest = ns
            used = True
        if used:
            ends.append(parse_iso(w["end"]))
            sources.append(prov.provenance("Anunț STPT, citit de noi", c.get("createdAt") or iso(at),
                                           c.get("sourceUrl"), None,
                                           f"lucrări: {c['title']['ro']}; analiză cu deciziile oamenilor aplicate"))

    day = _timetable_day(sid, at)
    for (r, d), nxt in (day or {}).items():
        if (r, d) in lines:
            continue
        lines[(r, d)] = StopLine(routeId=r, shortName=short(r), directionId=d, headsign=None, stops="yes", reason=None,
                                 nextDepartureAt=iso(from_unix(nxt)) if nxt else None)
    for ln in lines.values():
        if ln.headsign is None:
            p = gtfs.stop_patterns().get((ln.routeId, ln.directionId))
            ln.headsign = getattr(p, "headsign", None) if p else None

    ordered = sorted(lines.values(), key=lambda ln: (ln.stops != "no", ln.stops != "unconfirmed", ln.shortName, ln.directionId))
    any_no = any(ln.stops == "no" for ln in ordered)
    any_yes = any(ln.stops == "yes" for ln in ordered)
    if any_no:
        state_ = "partial" if any_yes else "suspended"
        if day is None:
            state_ = "partial"      # the timetable of the day is unknown: we only know the lines the notice names
    elif day is None and not ordered:
        state_ = "unknown"
    else:
        state_ = "normal"
    near = nearest if nearest and nearest["stopId"] != sid and any_no else None
    sentence = build_sentence(stop["name"], state_, ordered, near, max(ends) if ends else None)
    sources = [load_network().provenance, imp.current_timetable().provenance, *sources]
    return StopStatus(stopId=sid, name=stop["name"], location=stop["location"], at=iso(at), state=state_, lines=ordered,
                      nearestServed=near, sentence=sentence, liveFeed=live_feed_check(),
                      nextStepFree=_next_step_free(sid), provenance=sources)
