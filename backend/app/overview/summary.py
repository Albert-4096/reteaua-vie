"""Step 0 overview (SPEC §6.10): the KPI strip at a given time (default the demo clock).

- activeClosures:   published closures whose window contains `at`.
- upcomingClosures: published closures that start within 7 days after `at`.
- ghostDeparturesToday: scheduled departures lost on the calendar day of `at`
  in the published closures active that day (their lost rows, counted on the
  timetable each closure counts on); null if a window lies outside every feed.
- vehiclesLive / vehiclesAt: the newest recorded snapshot. On the demo clock it
  is shown with its real time; on the real clock it is null once older than 60 s.
- compliance: the counts of M7's ComplianceReport; null while M7 serves none.
- missingLines (O2): lines with no vehicle in our recording, the last 60 min of the
  real clock (`live`) and the prepared case_l23 (`prepared`); never the demo clock.
"""

from __future__ import annotations

import importlib
import logging
from datetime import datetime, timedelta, timezone

from app.common import state, vehicles
from app.common import provenance as prov
from app.common.timeutil import iso, local_midnight, parse_iso
from app.config import TZ, get_settings, now, real_now
from app.m1_disruption import impact as imp
from app.overview.closures import summarize

log = logging.getLogger("reteaua_vie.overview")

UPCOMING_DAYS = 7
LIVE_MAX_AGE_SEC = 60


def _published() -> list[dict]:
    return [c for c in state.list_all("closures") if c.get("status") == "published"]


def _window(c: dict) -> tuple[datetime, datetime]:
    return parse_iso(c["window"]["start"]), parse_iso(c["window"]["end"])


def ghost_departures(closures: list[dict], day_start: datetime, day_end: datetime) -> tuple[int | None, list]:
    """Departures lost in [day_start, day_end) by these closures, and the timetables used."""
    total = 0
    provs = []
    for c in closures:
        ws, we = _window(c)
        s, e = max(ws, day_start), min(we, day_end)
        if s >= e:
            continue
        analysis = state.read("closures", c["id"], state.PART_ANALYSIS) or {}
        lost = {imp.row_key(r) for r in analysis.get("stops") or [] if imp.counts_as_lost(r)}
        if not lost:
            continue
        tt = imp.timetable_for_closure(c)
        cw = imp.count_window(s, e, tt)
        counts = imp.departure_counts(cw, tt)
        if counts is None or cw.note:
            return None, [imp.timetable_provenance(tt, cw)]  # part of the day outside the feed: unknown
        total += sum(counts.get(k, 0) for k in lost)
        provs.append(imp.timetable_provenance(tt, cw))
    return total, provs


def _compliance() -> dict | None:
    """Counts from M7's ComplianceReport, if the module serves one."""
    for name, fn in (("app.m7_compliance.compliance", "report"),):
        try:
            mod = importlib.import_module(name)
            from app.m7_compliance.exports import mounted_paths
            report = getattr(mod, fn)(mounted_paths())
        except (ImportError, AttributeError):
            continue
        except Exception:  # noqa: BLE001 - the overview must not fail because of M7
            log.exception("M7 compliance report failed")
            return None
        data = report.model_dump() if hasattr(report, "model_dump") else report
        statuses = [o.get("status") for o in data.get("obligations") or []]
        return {k: statuses.count(k) for k in ("covered", "partial", "missing")}
    return None


def _missing_lines(provenance: list) -> dict:
    """O2 counts and top rows; a part that fails is null, the overview never fails for it."""
    from app.live import missing

    out: dict = {"live": None, "prepared": None}
    for key, run in (("live", lambda: missing.detect(*missing.live_window())),
                     ("prepared", lambda: missing.prepared("case_l23"))):
        try:
            result = run()
        except Exception:  # noqa: BLE001
            log.exception("O2 missing lines (%s) failed", key)
            continue
        out[key] = missing.brief(result)
        provenance.append(result["provenance"][1])  # the recording window read (the GTFS entry is [0])
        if key == "live":
            provenance.append(result["provenance"][2])  # the method
    return out


def overview(at: datetime | None = None) -> dict:
    at = (at or now()).astimezone(TZ)
    published = _published()
    active, upcoming = [], []
    for c in published:
        ws, we = _window(c)
        if ws <= at < we:
            active.append((ws, c))
        elif at < ws <= at + timedelta(days=UPCOMING_DAYS):
            upcoming.append((ws, c))
    day_start = local_midnight(at.date())
    day_end = local_midnight(at.date() + timedelta(days=1))
    ghost, gt_prov = ghost_departures(published, day_start, day_end)

    provenance = [prov.state_provenance(real_now())]
    provenance += gt_prov
    snap = vehicles.newest_snapshot()
    vehicles_live = vehicles_at = None
    if snap is not None:
        t = vehicles.snapshot_time(snap)
        age = (datetime.now(timezone.utc) - t).total_seconds()
        if get_settings().demo_now is not None or age <= LIVE_MAX_AGE_SEC:
            vehicles_live = sum(1 for v in snap.get("vehicles") or [] if v.get("lat") is not None)
            vehicles_at = iso(t)
            note = (f"Cel mai nou instantaneu înregistrat, {iso(t)} (ora reală, nu ora simulată) / newest "
                    f"recorded snapshot, real time" if get_settings().demo_now is not None
                    else f"Instantaneu de acum {int(age)} s / snapshot {int(age)} s old")
            provenance.append(prov.vehicles_provenance(t, note))
        else:
            provenance.append(prov.vehicles_provenance(
                t, f"Ultimul instantaneu are {int(age)} s (> {LIVE_MAX_AGE_SEC} s): necunoscut / stale"))
    missing_lines = _missing_lines(provenance)
    compliance = _compliance()
    if compliance is None:
        provenance.append(prov.provenance("Rețeaua Vie M7, conformitate / compliance", real_now(), None, None,
                                          "M7 nu servește încă raportul: necunoscut / not served yet"))
    return {
        "at": iso(at),
        "activeClosures": [summarize(c).model_dump() for _, c in sorted(active, key=lambda x: (x[0], x[1]["id"]))],
        "upcomingClosures": [summarize(c).model_dump() for _, c in
                             sorted(upcoming, key=lambda x: (x[0], x[1]["id"]))],
        "ghostDeparturesToday": ghost,
        "vehiclesLive": vehicles_live,
        "vehiclesAt": vehicles_at,
        "compliance": compliance,
        "missingLines": missing_lines,
        "provenance": [p.model_dump() if hasattr(p, "model_dump") else p for p in provenance],
    }
