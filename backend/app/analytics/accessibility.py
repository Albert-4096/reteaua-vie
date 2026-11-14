"""R6: step-free vehicles, measured from the vehicle recording.

(a) Per line and local hour: the share of recorded trips whose vehicle the City Hall feed flags
    wheelchair=true. Share = flagged trips / trips with a known flag; n is always given.
(b) Per stop: the typical wait for the next step-free vehicle, from L0 stop events of those trips
    (wait of a random arrival = sum(gap^2) / (2 sum(gap)) over gaps up to 90 min), and the
    nearest signalised crossing within 100 m with its OSM sound tag.
We say nothing about the stop itself: the GTFS has no wheelchair field.
"""

from __future__ import annotations

import time
from functools import lru_cache

import numpy as np
import pandas as pd

from app.analytics import crossings, recording
from app.common import gtfs
from app.common import provenance as prov
from app.common.geo import project_lonlats
from app.common.timeutil import iso
from app.config import TZ
from app.models.base import I18n
from app.observed import store

MAX_GAP_MIN = 90.0
MIN_EVENTS = 3
TTL_SEC = 1800

METHOD = I18n(
    ro=("Ponderea curselor înregistrate al căror vehicul are în fluxul Primăriei wheelchair=true, pe linie și oră "
        "(ora primei raportări a cursei, ora locală). O cursă = (cursă, vehicul, zi de serviciu); rapoartele "
        "repetate (același vehicul, același updatedAt) contează o dată. Cursele fără indicator sunt numărate "
        "separat și nu intră în pondere. Așteptarea la stație: din evenimentele de oprire ale orarului observat "
        "(L0) ale curselor accesibile; așteptarea tipică a unui sosit la întâmplare = Σ(pauză²) / (2 Σ pauză), "
        f"pe pauze de cel mult {MAX_GAP_MIN:.0f} min, doar la stațiile cu cel puțin {MIN_EVENTS} evenimente."),
    en=("Share of recorded trips whose vehicle the City Hall feed flags wheelchair=true, per line and local hour "
        "(hour of the trip's first report). A trip = (trip, vehicle, service day); repeated reports count once. "
        "Trips without the flag are counted apart and left out of the share. Stop wait: from L0 stop events of "
        f"the step-free trips; wait of a random arrival = sum(gap^2) / (2 sum gap), gaps up to {MAX_GAP_MIN:.0f} "
        f"min, only for stops with at least {MIN_EVENTS} events."))
CAVEAT = I18n(
    ro=("Vehicul marcat accesibil în fluxul Primăriei; stația nu e verificată (GTFS nu are câmpuri de accesibilitate). "
        "Doar vineri după-amiază și weekend: fără extrapolare la zilele lucrătoare."),
    en=("Vehicle flagged step-free in the City Hall feed; the stop itself is not verified (the GTFS has no "
        "accessibility fields). Friday afternoon and weekend only: no extrapolation to weekdays."))

_MODE = {"0": "tram", "3": "bus", "11": "trolleybus"}
_memo: dict = {}


def _share(a: int, n: int) -> float | None:
    return round(a / n, 3) if n else None


def _runs() -> tuple[pd.DataFrame, object, object]:
    """Trip runs with a verdict column `sf` (True / False / None), cached for TTL_SEC."""
    hit = _memo.get("runs")
    if hit and time.monotonic() - hit[0] < TTL_SEC:
        return hit[1]
    df, first, last = recording.trip_runs()
    df = recording.with_local_time(df)
    known = (df["n_true"] + df["n_false"]) > 0
    df["known"] = known
    df["sf"] = known & (df["n_true"] > df["n_false"])
    _memo["runs"] = (time.monotonic(), (df, first, last))
    return df, first, last


def recording_info(first, last) -> dict:
    if first is None or last is None:
        return {"from": None, "to": None, "hours": 0, "label": None}
    ro, en = store.label(first, last)
    return {"from": iso(first), "to": iso(last), "hours": max(1, round((last - first).total_seconds() / 3600)),
            "label": {"ro": ro, "en": en}}


def _hour_shares(df: pd.DataFrame) -> list[dict]:
    k = df[df["known"]]
    out = []
    for h, g in k.groupby("hour"):
        out.append({"hour": int(h), "trips": int(len(g)), "stepFree": int(g["sf"].sum()),
                    "share": _share(int(g["sf"].sum()), len(g))})
    return out


@lru_cache(maxsize=4)
def _names_for(sha: str) -> dict[str, tuple[str, str]]:
    r = gtfs.feed().routes
    return {row.route_id: (row.route_short_name or row.route_id, _MODE.get(str(row.route_type), "other"))
            for row in r.itertuples(index=False)}


def _route_names() -> dict[str, tuple[str, str]]:
    return _names_for(gtfs.feed().sha256)


def provenances(first, last, extra_note: str | None = None) -> list:
    ro = recording_info(first, last)["label"]
    note = (ro or {}).get("ro", "")
    out = [prov.vehicles_provenance(last, note + (f"; {extra_note}" if extra_note else ""))] if last else []
    out.append(gtfs.feed().provenance)
    return out


def lines_report() -> dict:
    df, first, last = _runs()
    names = _route_names()
    known = df[df["known"]]
    lines = []
    for rid, g in df.groupby("route"):
        k = g[g["known"]]
        short, mode = names.get(rid, (rid, "other"))
        lines.append({"routeId": rid, "shortName": short, "mode": mode, "trips": int(len(k)),
                      "stepFree": int(k["sf"].sum()), "share": _share(int(k["sf"].sum()), len(k)),
                      "unknown": int(len(g) - len(k)), "vehicles": int(g["vid"].nunique()),
                      "hours": _hour_shares(g)})
    lines.sort(key=lambda r: (r["shortName"].zfill(4) if r["shortName"].isdigit() else r["shortName"]))
    v = df.groupby("vid").agg(known=("known", "any"), sf=("n_true", lambda s: bool((s > 0).any())))
    nk = int(v["known"].sum())
    fleet = {"vehicles": nk, "stepFree": int((v["known"] & v["sf"]).sum()),
             "share": _share(int((v["known"] & v["sf"]).sum()), nk), "unknown": int(len(v) - nk)}
    total = {"hour": -1, "trips": int(len(known)), "stepFree": int(known["sf"].sum()),
             "share": _share(int(known["sf"].sum()), len(known))} if len(known) else None
    return {"recording": recording_info(first, last), "trips": total, "fleet": fleet,
            "byHour": _hour_shares(df), "lines": lines, "method": METHOD.model_dump(), "caveat": CAVEAT.model_dump(),
            "provenance": [p.model_dump() for p in provenances(first, last)]}


# --- stops -------------------------------------------------------------------------------------


def _wait_min(ts: np.ndarray) -> float | None:
    """Typical wait of a random arrival, minutes, from sorted event times (unix s)."""
    if len(ts) < MIN_EVENTS:
        return None
    gaps = np.diff(np.sort(ts)) / 60.0
    gaps = gaps[(gaps > 0) & (gaps <= MAX_GAP_MIN)]
    return round(float((gaps ** 2).sum() / (2 * gaps.sum())), 1) if len(gaps) else None


def stops_table() -> tuple[pd.DataFrame, object, object]:
    hit = _memo.get("stops")
    if hit and time.monotonic() - hit[0] < TTL_SEC:
        return hit[1]
    runs, first, last = _runs()
    ev = store.events()
    f = gtfs.feed()
    st = f.stops[["stop_id", "stop_name", "stop_lat", "stop_lon"]].copy()
    st["lat"], st["lon"] = st["stop_lat"].astype(float), st["stop_lon"].astype(float)
    xy = project_lonlats(zip(st["lon"], st["lat"]))
    st["crossing"] = crossings.nearest(xy)
    rows = {}
    if len(ev) and len(runs):
        flag = runs[runs["known"]][["trip", "vid", "sdate", "sf"]]
        e = ev[["trip_id", "vehicle_id", "service_date", "stop_id", "route_id", "event_ts"]].copy()
        e["vehicle_id"] = e["vehicle_id"].astype(str)
        e["service_date"] = e["service_date"].astype(str)
        e = e.merge(flag, left_on=["trip_id", "vehicle_id", "service_date"], right_on=["trip", "vid", "sdate"],
                    how="left")
        for sid, g in e.groupby("stop_id"):
            sf = g[g["sf"] == True]  # noqa: E712 - NaN-safe
            rows[sid] = {"stepFreeWaitMin": _wait_min(sf["event_ts"].to_numpy(float)),
                         "anyWaitMin": _wait_min(g["event_ts"].to_numpy(float)),
                         "stepFreeEvents": int(len(sf)), "allEvents": int(len(g)),
                         "lines": sorted(set(sf["route_id"]))}
    st["acc"] = [rows.get(s) for s in st["stop_id"]]
    _memo["stops"] = (time.monotonic(), (st, first, last))
    return st, first, last


def stop_record(r, first, last, names=None) -> dict:
    names = names or _route_names()
    acc = r["acc"] or {}
    return {"stopId": r["stop_id"], "name": r["stop_name"], "location": [r["lon"], r["lat"]],
            "stepFreeWaitMin": acc.get("stepFreeWaitMin"), "anyWaitMin": acc.get("anyWaitMin"),
            "stepFreeEvents": acc.get("stepFreeEvents", 0), "allEvents": acc.get("allEvents", 0),
            "nextStepFreeLines": [names.get(x, (x, ""))[0] for x in acc.get("lines", [])],
            "crossing": r["crossing"], "recording": recording_info(first, last)}


def stop_report(stop_id: str) -> dict | None:
    st, first, last = stops_table()
    hit = st[st["stop_id"] == stop_id]
    if hit.empty:
        return None
    rec = stop_record(hit.iloc[0], first, last)
    rec.update(method=METHOD.model_dump(), caveat=CAVEAT.model_dump(),
               provenance=[p.model_dump() for p in provenances(first, last)] + [crossings.provenance().model_dump()])
    return rec


def layer(bbox=None) -> dict:
    st, first, last = stops_table()
    names = _route_names()
    feats = []
    for _, r in st.iterrows():
        if bbox and not (bbox[0] <= r["lon"] <= bbox[2] and bbox[1] <= r["lat"] <= bbox[3]):
            continue
        p = stop_record(r, first, last, names)
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": p.pop("location")},
                      "properties": {k: p[k] for k in ("stopId", "name", "stepFreeWaitMin", "anyWaitMin",
                                                       "stepFreeEvents", "allEvents", "crossing")}})
    return {"type": "FeatureCollection", "layer": "accessibility", "features": feats,
            "provenance": [p.model_dump() for p in provenances(first, last)] + [crossings.provenance().model_dump()]}
