"""GET /api/observed/summary: what L0 holds, how far it reaches and how good the match is."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from app.common import gtfs
from app.common import provenance as prov
from app.common.timeutil import iso, parse_iso
from app.models.base import I18n
from app.observed import build, store
from app.observed.models import ObservedGap, ObservedHours, ObservedQuality, ObservedSummary

MATCH_SHARE = 0.8
INSIDE_MARGIN_SEC = 300

METHOD = I18n(
    ro=("Orar observat: sosirea și plecarea din stație din rapoartele „oprit în stație” (STOPPED_AT) ale "
        "vehiculelor, la mijlocul intervalului dintre două rapoarte; o stație trecută între două rapoarte "
        f"primește o oră interpolată pe traseul GTFS. Nicio oră când rapoartele sunt la peste "
        f"{build.MAX_GAP_SEC} s distanță. Rapoartele repetate (același vehicul, același updatedAt) contează o dată."),
    en=("Observed timetable: stop arrival and departure from the vehicles' STOPPED_AT reports, at the midpoint "
        "between two reports; a stop passed between two reports gets a time interpolated along the GTFS shape. "
        f"No time when the reports are more than {build.MAX_GAP_SEC} s apart. Repeated reports (same vehicle, "
        "same updatedAt) count once."),
)


def _median(x: pd.Series) -> float | None:
    x = x.dropna()
    return round(float(np.median(x)), 1) if len(x) else None


def _share(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def quality(ev: pd.DataFrame, first: float, last: float, gaps: list[ObservedGap]) -> ObservedQuality:
    trips = ev.groupby(["trip_id", "service_date"]).agg(
        n=("n_stops", "first"), m=("stop_index", "nunique"), start=("trip_sched_start", "first"),
        end=("trip_sched_end", "first"), last_ev=("event_ts", "max"))
    good = trips["m"] / trips["n"] >= MATCH_SHARE
    inside = (trips["start"] >= first + INSIDE_MARGIN_SEC) & (trips["end"] <= last - INSIDE_MARGIN_SEC)
    obs = ev[~ev["interpolated"].astype(bool)]
    diff = (obs["delay_sec"] - obs["feed_delay_sec"]).dropna()
    interp = ev[ev["interpolated"].astype(bool)]
    diff_i = (interp["delay_sec"] - interp["feed_delay_sec"]).dropna()
    sd = pd.to_datetime(trips.index.get_level_values("service_date")).date
    midnight = np.array([build.tt.service_base(d + timedelta(days=1)) for d in sd]) if len(trips) else np.zeros(0)
    return ObservedQuality(
        tripsObserved=int(len(trips)), tripsWith80PctStops=int(good.sum()),
        shareWith80PctStops=_share(int(good.sum()), len(trips)),
        tripsInsideRecording=int(inside.sum()),
        shareWith80PctStopsInside=_share(int((good & inside).sum()), int(inside.sum())),
        delayPairs=int(len(diff)), medianAbsDelayDiffSec=_median(diff.abs()), medianDelayDiffSec=_median(diff),
        medianAbsDelayDiffSecInterpolated=_median(diff_i.abs()),
        tripsAfterMidnight=int((trips["last_ev"].to_numpy(float) >= midnight).sum()),
        maxGapSec=build.MAX_GAP_SEC, gaps=gaps)


def _gaps(hours: dict) -> list[ObservedGap]:
    out = [ObservedGap(**{"from": g[0]}, seconds=g[1]) for h in hours.values() for g in h.get("gaps", [])]
    recs = sorted((parse_iso(h["first"]), parse_iso(h["last"])) for h in hours.values() if h.get("first"))
    for (_f0, l0), (f1, _l1) in zip(recs, recs[1:]):
        sec = int((f1 - l0).total_seconds())
        if sec > build.GAP_NOTE_SEC:
            out.append(ObservedGap(**{"from": iso(l0)}, seconds=sec))
    return sorted(out, key=lambda g: g.from_)


def _report_ids() -> tuple[int, int]:
    """(vehicles, trip ids) seen in the built hours' reports."""
    vids, trips = set(), set()
    for s in store.built_stems():
        p = build.out_dir() / "reports" / f"{s}.parquet"
        if p.is_file():
            t = pq.read_table(p, columns=["vid", "trip"])
            vids.update(t.column("vid").to_pylist())
            trips.update(t.column("trip").to_pylist())
    return len(vids), len(trips)


_memo: dict[tuple, ObservedSummary] = {}


def summary() -> ObservedSummary:
    """The summary of the built hours; `hours.pending` is counted fresh on every call."""
    pending = len(build.pending_hours()) + 1  # + the hour being recorded
    key = store._stamp()
    if key not in _memo:
        if len(_memo) > 4:
            _memo.clear()
        _memo[key] = _summary()
    out = _memo[key]
    if out.hours is None:
        return out
    return out.model_copy(update={"hours": out.hours.model_copy(update={"pending": pending})})


def _summary() -> ObservedSummary:
    m = store.manifest()
    hours = m.get("hours", {})
    cov = store.coverage()
    if cov is None:
        return ObservedSummary(hours=None, snapshots=0, reports=0, vehicles=0, routes=0, trips=0, stopEvents=0,
                               interpolatedEvents=0, interpolatedShare=None, dwellEvents=0, medianDwellSec=None,
                               segments=0, quality=None, label=None, method=METHOD, provenance=[])
    ev = store.events()
    n_vehicles, n_trips = _report_ids()
    n_ev = int(len(ev))
    n_int = int(ev["interpolated"].astype(bool).sum()) if n_ev else 0
    first, last = cov["first"], cov["last"]
    routes = {r for h in hours.values() for r in h.get("routes", [])}
    note = f"{cov['labelRo']}; {len(hours)} ore construite în orarul observat / hours built into L0"
    provs = [prov.vehicles_provenance(last, note)]
    days = sorted({date.fromisoformat(d) for d in ev["service_date"].unique()}) if n_ev else []
    seen = set()
    for d in days:
        f = gtfs.feed(at=d)
        if f.sha256 not in seen:
            seen.add(f.sha256)
            provs.append(f.provenance)
    out = ObservedSummary(
        hours=ObservedHours(**{"from": iso(first)}, to=iso(last),
                            recordedHours=round((last - first).total_seconds() / 3600),
                            built=len(hours), pending=0),
        snapshots=sum(int(h.get("snapshots", 0)) for h in hours.values()),
        reports=sum(int(h.get("reports", 0)) for h in hours.values()),
        vehicles=n_vehicles, routes=len(routes), trips=n_trips, stopEvents=n_ev, interpolatedEvents=n_int,
        interpolatedShare=_share(n_int, n_ev), dwellEvents=int(ev["dwell_sec"].notna().sum()) if n_ev else 0,
        medianDwellSec=_median(ev["dwell_sec"]) if n_ev else None,
        segments=sum(int(h.get("segments", 0)) for h in hours.values()),
        quality=quality(ev, first.timestamp(), last.timestamp(), _gaps(hours)) if n_ev else None,
        label=I18n(ro=cov["labelRo"], en=cov["labelEn"]), method=METHOD, provenance=provs)
    return out
