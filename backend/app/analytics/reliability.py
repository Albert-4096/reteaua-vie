"""L3: line reliability, measured from the observed timetable (L0) and the recording.

Per line and local hour, always with n:
  punctuality  the delay of observed stop events (not interpolated): classes and a 95 % interval from
               a bootstrap that resamples whole trip runs (a trip is one block), „neconcludent” when small;
  headway      at one reference stop per line and direction (the one with most observed events) the real gap
               between consecutive scheduled trips, both observed, against the scheduled gap: cv and the extra
               wait (Σh²/2Σh real minus scheduled);
  bunching     an observed stop event with another vehicle of the same line and direction within BUNCH_SEC at
               the same stop, unless the timetable itself puts them that close;
  trips        O2's rule (`app.live.missing`): trips observed or with no vehicle in the live data, by start hour.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

import numpy as np
import pandas as pd

from app.analytics import accessibility
from app.common import gtfs
from app.config import TZ, get_settings
from app.live import missing as o2
from app.models.base import I18n
from app.observed import store

EARLY_SEC, ON_TIME_MAX_SEC, LATE_MAX_SEC = -60, 300, 600
BUNCH_SEC = 120
MIN_TRIPS, MIN_EVENTS = 10, 30
BOOT_N = 300
TTL_SEC = 300
CACHE_VERSION = 1

WORDING = I18n(ro="Estimare din datele live, nu raportul oficial.", en="Estimate from the live data, not the official report.")
METHOD = I18n(
    ro=("Din orarul observat (L0), construit din rapoartele vehiculelor din fluxul Primăriei. Punctualitate: "
        f"întârzierea la opriri observate (nu interpolate); clase: devansat sub {EARLY_SEC} s, la timp până la "
        f"+{ON_TIME_MAX_SEC} s, întârziat până la +{LATE_MAX_SEC} s, peste. Intervalul de 95 % pentru „la timp” vine "
        f"dintr-un bootstrap cu o cursă ca bloc ({BOOT_N} extrageri); „neconcludent” sub {MIN_TRIPS} curse sau "
        f"{MIN_EVENTS} opriri. Interval: la o stație de referință pe linie și direcție, diferența reală dintre curse "
        "consecutive din orar, ambele observate, față de cea din orar; așteptare în plus = Σh²/2Σh real minus orar. "
        f"Pluton: două vehicule ale aceleiași linii și direcții la aceeași stație la cel mult {BUNCH_SEC} s, dacă "
        "orarul nu le pune la fel de aproape. Curse observate față de orar: regula O2 (fără vehicul în datele "
        "live, nu „neefectuată”)."),
    en=("From the observed timetable (L0) built from the City Hall vehicle reports. Delay classes, a trip-block "
        "bootstrap interval, headway at a reference stop against the timetable, bunching within "
        f"{BUNCH_SEC} s and trips by O2's rule."))
CAVEAT = I18n(
    ro=("Estimare din datele live, nu raportul oficial; doar vineri după-amiază și weekend, fără extrapolare la zilele "
        "lucrătoare. Nu arată nicio vină a cuiva și nu e o clasificare a curselor: doar SMTT le încadrează."),
    en=("Estimate from the live data, not the official report; Friday afternoon and weekend only. It assigns no "
        "blame and does not classify trips: only SMTT does."))
_memo: dict = {}


def _share(a, n):
    return round(float(a) / n, 3) if n else None


def _punct(g: pd.DataFrame, rng: np.random.Generator) -> dict:
    n = int(len(g))
    if not n:
        return {"n": 0, "trips": 0, "medianSec": None, "p90Sec": None, "early": None, "onTime": None, "late": None,
                "veryLate": None, "ci": None, "conclusive": False}
    d = g["delay_sec"].to_numpy(float)
    cls = {"early": d < EARLY_SEC, "onTime": (d >= EARLY_SEC) & (d <= ON_TIME_MAX_SEC),
           "late": (d > ON_TIME_MAX_SEC) & (d <= LATE_MAX_SEC), "veryLate": d > LATE_MAX_SEC}
    per = g.assign(ot=cls["onTime"]).groupby(["trip_id", "service_date"])["ot"].agg(["sum", "count"])
    k = len(per)
    ci = None
    if k >= 2:
        s, c = per["sum"].to_numpy(float), per["count"].to_numpy(float)
        pick = rng.integers(0, k, (BOOT_N, k))
        r = s[pick].sum(1) / c[pick].sum(1)
        ci = [round(float(np.percentile(r, 2.5)), 3), round(float(np.percentile(r, 97.5)), 3)]
    return {"n": n, "trips": k, "medianSec": round(float(np.median(d)), 1), "p90Sec": round(float(np.percentile(d, 90)), 1),
            **{key: _share(v.sum(), n) for key, v in cls.items()}, "ci": ci,
            "conclusive": bool(k >= MIN_TRIPS and n >= MIN_EVENTS)}


def _awt(h: np.ndarray) -> float | None:
    return float((h ** 2).sum() / (2 * h.sum())) if len(h) and h.sum() > 0 else None


def _head(p: pd.DataFrame) -> dict:
    empty = {"pairs": 0, "refStopId": None, "medianRealMin": None, "medianSchedMin": None, "cvReal": None,
             "cvSched": None, "ewtMin": None}
    if p.empty:
        return empty
    real, sched = p["real_hw"].to_numpy(float) / 60, p["sched_hw"].to_numpy(float) / 60
    a, b = _awt(real), _awt(sched)
    ref = p["stop_id"].mode()
    return {"pairs": int(len(p)), "refStopId": str(ref.iloc[0]) if len(ref) else None,
            "medianRealMin": round(float(np.median(real)), 1), "medianSchedMin": round(float(np.median(sched)), 1),
            "cvReal": round(float(real.std() / real.mean()), 2) if real.mean() > 0 else None,
            "cvSched": round(float(sched.std() / sched.mean()), 2) if sched.mean() > 0 else None,
            "ewtMin": round(a - b, 1) if a is not None and b is not None else None}


def _bunch(g: pd.DataFrame) -> dict:
    n = int(len(g))
    b = int(g["bunched"].sum())
    return {"events": n, "bunched": b, "share": _share(b, n), "thresholdSec": BUNCH_SEC}


def _trips(g: pd.DataFrame) -> dict:
    ob, mi = int((g["res"] == "observed").sum()), int((g["res"] == "missed").sum())
    return {"scheduled": ob + mi, "observed": ob, "missed": mi, "unknown": int((g["res"] == "unknown").sum()),
            "share": _share(ob, ob + mi)}


def _observed_events() -> pd.DataFrame:
    ev = store.events()
    ev = ev[(~ev["interpolated"].astype(bool)) & ev["arr"].notna() & ev["delay_sec"].notna()].copy()
    ev["hour"] = pd.to_datetime(ev["arr"], unit="s", utc=True).dt.tz_convert(TZ).dt.hour
    ev["sd"] = ev["service_date"].str.replace("-", "").astype(int)
    return ev


def _bunching(ev: pd.DataFrame) -> pd.Series:
    e = ev.sort_values(["route_id", "direction_id", "stop_id", "arr"])
    key = [e["route_id"], e["direction_id"], e["stop_id"]]
    same = (e.groupby(["route_id", "direction_id", "stop_id"]).cumcount() > 0)
    gap = e["arr"].diff()
    sgap = e["sched_arr"].diff()
    near = same & (gap <= BUNCH_SEC) & (e["vehicle_id"] != e["vehicle_id"].shift()) & (sgap > BUNCH_SEC)
    near_next = near.shift(-1, fill_value=False)
    # the next row's `near` only counts inside the same group (`same` of the next row is already in `near`)
    return (near | near_next).reindex(ev.index)


def _headway_pairs(ev: pd.DataFrame) -> pd.DataFrame:
    if ev.empty:
        return pd.DataFrame()
    ref = (ev[ev["stop_index"] >= 1].groupby(["route_id", "direction_id", "stop_id"]).size().rename("n").reset_index()
           .sort_values("n", ascending=False).drop_duplicates(["route_id", "direction_id"]))
    day = datetime.fromtimestamp(float(ev["arr"].min()), TZ).date()
    idx = gtfs._index(gtfs.feed(day).sha256)
    s = idx.assign(stop_id=idx["stop_id"].astype(str), route_id=idx["route_id"].astype(str),
                   direction_id=idx["direction_id"].astype(int))
    s = s.merge(ref[["route_id", "direction_id", "stop_id"]], on=["route_id", "direction_id", "stop_id"])
    s = s.sort_values(["route_id", "direction_id", "stop_id", "service_date", "dep_ts"])
    g = s.groupby(["route_id", "direction_id", "stop_id", "service_date"])
    s["next_trip"] = g["trip_id"].shift(-1)
    s["sched_hw"] = g["dep_ts"].shift(-1) - s["dep_ts"]
    s = s.dropna(subset=["next_trip"])
    s = s[(s["sched_hw"] > 0) & (s["sched_hw"] <= 5400)]
    obs = ev[["trip_id", "sd", "stop_id", "arr"]].rename(columns={"sd": "service_date"})
    s = s.merge(obs, on=["trip_id", "service_date", "stop_id"]).merge(
        obs.rename(columns={"trip_id": "next_trip", "arr": "arr1"}), on=["next_trip", "service_date", "stop_id"])
    s["real_hw"] = s["arr1"] - s["arr"]
    s = s[(s["real_hw"] > 0) & (s["real_hw"] <= 5400)]
    s["hour"] = pd.to_datetime(s["arr"], unit="s", utc=True).dt.tz_convert(TZ).dt.hour
    return s


def _o2_trips(cov: dict) -> pd.DataFrame:
    start, end = cov["first"], cov["last"]
    f = gtfs.feed(start)
    trips, _hw = o2.scheduled_trips(f, start, end)
    snaps, _files = o2.recorded(start, end)
    if trips.empty:
        return trips.assign(res=[], hour=[])
    s_ts, e_ts = start.timestamp(), end.timestamp()
    out = trips.assign(res=o2.classify_trips(trips, snaps, s_ts, e_ts))
    out["hour"] = pd.to_datetime(out["start_ts"], unit="s", utc=True).dt.tz_convert(TZ).dt.hour
    return out


def report() -> dict:
    hit = _memo.get("report")
    stamp = store._stamp()
    if hit and hit[1] == stamp and time.monotonic() - hit[0] < TTL_SEC:
        return hit[2]
    disk = get_settings().cache_dir / "analytics" / f"reliability_{CACHE_VERSION}_{stamp[0]}_{stamp[1]}.json"
    if disk.is_file():
        out = json.loads(disk.read_text(encoding="utf-8"))
        _memo["report"] = (time.monotonic(), stamp, out)
        return out
    cov = store.coverage()
    names = accessibility._route_names()
    th = {"earlySec": EARLY_SEC, "onTimeMaxSec": ON_TIME_MAX_SEC, "lateMaxSec": LATE_MAX_SEC,
          "bunchingSec": BUNCH_SEC, "minTrips": MIN_TRIPS, "minEvents": MIN_EVENTS}
    if cov is None:
        raise RuntimeError("L0 has no built hour yet (în lucru)")
    ev = _observed_events()
    ev["bunched"] = _bunching(ev)
    pairs = _headway_pairs(ev)
    trips = _o2_trips(cov)
    rng = np.random.default_rng(7)
    routes = sorted(set(ev["route_id"]) | set(trips["route_id"]))
    lines = []
    for rid in routes:
        e = ev[ev["route_id"] == rid]
        p = pairs[pairs["route_id"] == rid] if len(pairs) else pairs
        t = trips[trips["route_id"] == rid]
        hrs = []
        for h in sorted(set(e["hour"]) | set(t["hour"])):
            eh = e[e["hour"] == h]
            hrs.append({"hour": int(h), "punctuality": _punct(eh, rng),
                        "headway": _head(p[p["hour"] == h] if len(p) else p), "bunching": _bunch(eh),
                        "trips": _trips(t[t["hour"] == h])})
        short, mode = names.get(rid, (rid, "other"))
        lines.append({"routeId": rid, "shortName": short, "mode": mode, "punctuality": _punct(e, rng),
                      "headway": _head(p), "bunching": _bunch(e), "trips": _trips(t), "hours": hrs})
    lines.sort(key=lambda r: (r["shortName"].zfill(4) if r["shortName"].isdigit() else r["shortName"]))
    out = {"recording": accessibility.recording_info(cov["first"], cov["last"]), "thresholds": th, "lines": lines,
           "wording": WORDING.model_dump(), "method": METHOD.model_dump(), "caveat": CAVEAT.model_dump(),
           "provenance": [p.model_dump() for p in accessibility.provenances(cov["first"], cov["last"], "orar observat L0")]}
    _memo["report"] = (time.monotonic(), stamp, out)
    try:
        disk.parent.mkdir(parents=True, exist_ok=True)
        for old in disk.parent.glob(f"reliability_{CACHE_VERSION}_*.json"):
            old.unlink(missing_ok=True)
        disk.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return out
