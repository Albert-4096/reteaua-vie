"""A13: ETA for CityApp as GTFS-RT TripUpdates, from the newest recorded snapshot, with a back-test on L0.

Predictors for the arrival at a future stop of a vehicle that reports delay d now:
  timetable  the scheduled time;
  persist    scheduled + d  (the timetable moved by the delay the vehicle reports now).
Back-test on the recording (L0 stop events): "now" = an observed stop event with the delay the feed reported
there; the target = the first later observed stop whose scheduled time is at least H minutes after the scheduled
time of "now" (H = 5, 10, 15; at most SLACK_SEC more); error = predicted - observed arrival. We tried adding the
median delay growth of the stretches in between (L0 segment runs, learned on the other half of the trips): it was
worse than `persist` (median error 129/260/381 s against 68/93/117 s at 5/10/15 min), so it is not used.
The feed uses the predictor the back-test favours and says whether it beats the timetable on both the median and the
mean error at every horizon. No ETA for a vehicle whose last report is older than MAX_AGE_SEC; none at all when the
newest snapshot is older than MAX_STALE_SNAPSHOT_SEC.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from google.transit import gtfs_realtime_pb2 as rt

from app.analytics import accessibility
from app.common import gtfs, vehicles
from app.common.timeutil import iso
from app.config import TZ
from app.models.base import I18n
from app.observed import store

HORIZONS = (5, 10, 15)
SLACK_SEC = 240
MAX_AGE_SEC = 120
MAX_STALE_SNAPSHOT_SEC = 600
MAX_STOPS = 12
TTL_SEC = 300

METHOD = I18n(
    ro=("Pe înregistrare (orarul observat L0): „acum” = o oprire observată cu întârzierea raportată de flux; ținta = prima "
        "oprire observată ulterior al cărei orar e la cel puțin 5, 10 sau 15 min după „acum” (cel mult 4 min în plus); "
        "eroarea = ora prezisă minus ora observată. „Doar orarul” față de „orar + întârzierea de acum”."),
    en="Back-test on the recording (L0 stop events) against the observed arrival: timetable alone vs timetable + the delay reported now.")
_memo: dict = {}


def _runs() -> pd.DataFrame:
    ev = store.events()
    ev = ev[(~ev["interpolated"].astype(bool)) & ev["arr"].notna() & ev["feed_delay_sec"].notna()]
    return ev.sort_values(["trip_id", "service_date", "vehicle_id", "stop_sequence"])


def backtest() -> dict:
    stamp = store._stamp()
    hit = _memo.get("bt")
    if hit and hit[1] == stamp and time.monotonic() - hit[0] < TTL_SEC:
        return hit[2]
    cov = store.coverage()
    if cov is None:
        raise RuntimeError("L0 has no built hour yet (în lucru)")
    rows = []
    for _k, run in _runs().groupby(["trip_id", "service_date", "vehicle_id"], sort=False):
        sa, arr, d = (run[c].to_numpy(float) for c in ("sched_arr", "arr", "feed_delay_sec"))
        for h in HORIZONS:
            tgt = np.searchsorted(sa, sa + h * 60, side="left")
            idx = np.nonzero(tgt < len(sa))[0]
            idx = idx[(sa[tgt[idx]] - sa[idx]) <= h * 60 + SLACK_SEC]
            for i in idx:
                j = tgt[i]
                rows.append((h, arr[j] - sa[j], arr[j] - (sa[j] + d[i])))
    r = pd.DataFrame(rows, columns=["h", "tt", "persist"])
    cells, means = [], {"tt": [], "persist": []}
    for h in HORIZONS:
        x = r[r["h"] == h]
        c = {"horizonMin": h, "n": int(len(x))}
        for key, name in (("tt", "timetable"), ("persist", "persist")):
            c[f"{name}MedianAbsSec"] = round(float(x[key].abs().median()), 1) if len(x) else None
            c[f"{name}MeanAbsSec"] = round(float(x[key].abs().mean()), 1) if len(x) else None
            if len(x):
                means[key].append(float(x[key].abs().mean()))
        cells.append(c)
    chosen = "persist" if means["persist"] and means["persist"] and np.mean(means["persist"]) < np.mean(means["tt"] or [1e18]) else "timetable"
    beats = chosen == "persist" and all(
        c["persistMedianAbsSec"] is not None and c["persistMedianAbsSec"] < c["timetableMedianAbsSec"]
        and c["persistMeanAbsSec"] < c["timetableMeanAbsSec"] for c in cells)
    ro, en = store.label(cov["first"], cov["last"])
    nn = sum(c["n"] for c in cells)
    if beats:
        v = I18n(ro=f"Pe înregistrare ({ro}, {nn} predicții), orarul mutat cu întârzierea raportată are eroarea mediană și medie mai mică decât orarul singur la 5, 10 și 15 min.",
                 en=f"On the recording ({en}, {nn} predictions) the timetable moved by the reported delay has a smaller median and mean error than the timetable alone at 5, 10 and 15 min.")
    else:
        v = I18n(ro=f"Pe înregistrare ({ro}, {nn} predicții) estimarea nu bate orarul la toate orizonturile: nu afirmăm că e mai bună.",
                 en="On the recording the estimate does not beat the timetable at every horizon: we do not claim it is better.")
    out = {"recording": accessibility.recording_info(cov["first"], cov["last"]), "cells": cells, "chosen": chosen,
           "beatsTimetable": bool(beats), "verdict": v.model_dump(), "method": METHOD.model_dump(),
           "provenance": [p.model_dump() for p in accessibility.provenances(cov["first"], cov["last"], "orar observat L0")]}
    _memo["bt"] = (time.monotonic(), stamp, out)
    return out


# --- the live feed ----------------------------------------------------------------------------


def _trip_rows(st: pd.DataFrame, trip: str) -> pd.DataFrame:
    cache = _memo.setdefault("trips", {})
    key = (id(st), trip)
    if key not in cache:
        if len(cache) > 4000:
            cache.clear()
        cache[key] = st[st["trip_id"] == trip].sort_values("stop_sequence")[["stop_id", "stop_sequence", "arr_sec"]]
    return cache[key]


def build(now_ts: float | None = None) -> dict:
    """The TripUpdates of the newest snapshot; no trips when it is stale."""
    snap = vehicles.newest_snapshot()
    cov = store.coverage()
    chosen = backtest()["chosen"] if cov is not None else "timetable"
    label = None
    if cov is not None:
        a, b = store.label(cov["first"], cov["last"])
        label = {"ro": f"estimare, {a}", "en": f"estimate, {b}"}
    empty = {"at": None, "predictor": chosen, "skipped": 0, "trips": [], "label": label}
    if snap is None:
        return empty
    at = vehicles.snapshot_time(snap)
    if (now_ts if now_ts is not None else time.time()) - at.timestamp() > MAX_STALE_SNAPSHOT_SEC:
        return {**empty, "at": at}
    f = gtfs.feed(at)
    names = accessibility._route_names()
    days = [datetime(at.year, at.month, at.day, tzinfo=TZ) - timedelta(days=k) for k in (0, 1)]
    out, skipped = [], 0
    for v in snap.get("vehicles") or []:
        trip, seq, upd = v.get("tripId"), v.get("stopSequence"), v.get("updatedAt")
        if not trip or seq is None or upd is None:
            continue
        age = int(at.timestamp() - float(upd))
        if age > MAX_AGE_SEC or age < -30:
            skipped += 1
            continue
        g = _trip_rows(f.stop_times, trip)
        future = g[g["stop_sequence"] > int(seq)] if v.get("status") == "STOPPED_AT" else g[g["stop_sequence"] >= int(seq)]
        if future.empty:
            continue
        delay = float(v.get("delaySec") or 0)
        ref = float(future["arr_sec"].iloc[0])
        base = min(days, key=lambda b: abs(b.timestamp() + ref + delay - float(upd)))   # the service day it runs on
        rows, last = [], 0.0
        for q in future.head(MAX_STOPS).itertuples(index=False):
            sched = base.timestamp() + float(q.arr_sec)
            arr = sched + (delay if chosen == "persist" else 0.0)
            if arr < at.timestamp() - 60:
                continue
            arr = max(arr, last + 1)            # the feed spec wants strictly increasing times; the timetable repeats a minute
            last = arr
            rows.append({"stopId": q.stop_id, "stopSequence": int(q.stop_sequence),
                         "scheduledAt": iso(datetime.fromtimestamp(sched, TZ)), "arrivalAt": iso(datetime.fromtimestamp(arr, TZ)),
                         "delaySec": int(round(arr - sched)), "_arr": int(arr)})
        if rows:
            route = v.get("routeId")
            out.append({"tripId": trip, "routeId": route, "shortName": names.get(route, (route, ""))[0],
                        "directionId": v.get("directionId"), "vehicleId": str(v.get("id")), "reportAgeSec": age, "updates": rows})
    return {"at": at, "predictor": chosen, "skipped": skipped, "trips": out, "label": label}


def feed_bytes(data: dict) -> bytes:
    msg = rt.FeedMessage()
    msg.header.gtfs_realtime_version = "2.0"
    msg.header.incrementality = rt.FeedHeader.FULL_DATASET
    msg.header.timestamp = int((data["at"] or datetime.now(TZ)).timestamp())
    for t in data["trips"]:
        e = msg.entity.add()
        e.id = f"{t['tripId']}:{t['vehicleId']}"
        tu = e.trip_update
        tu.trip.trip_id = t["tripId"]
        tu.trip.route_id = t["routeId"]
        tu.trip.schedule_relationship = rt.TripDescriptor.SCHEDULED
        if t["directionId"] is not None:
            tu.trip.direction_id = int(t["directionId"])
        tu.vehicle.id = t["vehicleId"]
        tu.timestamp = msg.header.timestamp
        for u in t["updates"]:
            s = tu.stop_time_update.add()
            s.stop_sequence = u["stopSequence"]
            s.stop_id = u["stopId"]
            s.arrival.time = u["_arr"]
            s.arrival.delay = u["delaySec"]
            s.schedule_relationship = rt.TripUpdate.StopTimeUpdate.SCHEDULED
    return msg.SerializeToString()


def debug(data: dict) -> dict:
    bt = backtest() if store.coverage() is not None else None
    trips = [{**t, "updates": [{k: v for k, v in u.items() if not k.startswith("_")} for u in t["updates"]]} for t in data["trips"]]
    verdict = ("Pe înregistrare, această estimare bate orarul singur." if bt and bt["beatsTimetable"]
               else "Nu afirmăm că estimarea bate orarul: vezi `backtest.verdict`.")
    note = I18n(ro=f"Estimare, nu ora oficială. Fără ETA pentru un vehicul cu ultimul raport mai vechi de {MAX_AGE_SEC} s. {verdict}",
                en="Estimate, not the official time. No ETA for a vehicle without a recent report.")
    return {"at": iso(data["at"]) if data["at"] else None, "label": data["label"], "predictor": data["predictor"],
            "maxReportAgeSec": MAX_AGE_SEC, "skippedNoRecentReport": data["skipped"], "trips": trips, "backtest": bt,
            "note": note.model_dump()}
