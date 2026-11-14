"""Which GTFS trip does a check-in belong to? The sticker gives route + direction; the time (and, when the
phone shares it, the position at that moment) gives the trip. Thresholds are proposals, not measured."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
from shapely.geometry import Point

from app.cityapp import km
from app.common import gtfs
from app.common.city import load_network
from app.common.errors import invalid
from app.common.geo import project_lonlats
from app.common.timeutil import gtfs_service_start
from app.live import missing
from app.m1_disruption import impact as imp

MAX_OFF_ROUTE_M = 300.0      # proposal
MAX_GAP = timedelta(minutes=30)   # nearest trip by time, when none is in service at that moment
SPAN = timedelta(minutes=90)


def _stop_xy(stop_id: str):
    s = load_network().stop_by_id.get(stop_id)
    return project_lonlats([tuple(s["location"])])[0] if s else None


def resolve(route: str, direction: int, at: datetime, lat: float | None, lon: float | None) -> dict:
    f = gtfs.feed(at)
    trips, _ = missing.scheduled_trips(f, at - SPAN, at + SPAN)
    recs = trips[(trips.route_id == route) & (trips.direction_id.astype(int) == direction)].to_dict("records")
    ts = at.timestamp()
    if not recs:
        raise invalid("Nicio cursă a liniei în jurul orei: nu putem lega check-in-ul de o cursă.", code="NO_TRIP")
    in_service = [r for r in recs if r["start_ts"] <= ts <= r["end_ts"]]
    dist_m: float | None = None
    method = "time"
    chosen = None
    if lat is not None and lon is not None:
        shape = km._shape(imp.current_timetable(), route, direction)
        if shape is not None:
            p = Point(*project_lonlats([(lon, lat)])[0])
            dist_m = float(shape.distance(p))
            if dist_m > MAX_OFF_ROUTE_M:
                raise invalid("Poziție departe de traseu: check-in-ul nu e legat de nicio cursă.", code="FAR_FROM_ROUTE")
            along = shape.project(p)
            best = None
            for t in in_service:
                st = f.stop_times[f.stop_times.trip_id == t["trip_id"]].sort_values("stop_sequence")
                pos = []
                for sid in st.stop_id.astype(str):
                    xy = _stop_xy(sid)
                    pos.append(shape.project(Point(*xy)) if xy is not None else np.nan)
                pos = np.array(pos, dtype=float)
                ok = ~np.isnan(pos)
                if ok.sum() < 2:
                    continue
                base = gtfs_service_start(t["day"]).timestamp()
                sched = float(np.interp(ts - base, st.dep_sec.to_numpy()[ok], pos[ok]))
                if best is None or abs(sched - along) < best[0]:
                    best = (abs(sched - along), t)
            if best is not None:
                chosen, method = best[1], "position"
    if chosen is None:
        if in_service:   # the trip in service that left last: the same one for every phone until the next departure
            chosen = max(in_service, key=lambda r: r["start_ts"])
        else:            # the nearest trip by time
            chosen = min(recs, key=lambda r: min(abs(r["start_ts"] - ts), abs(ts - r["end_ts"])))
            if min(abs(chosen["start_ts"] - ts), abs(ts - chosen["end_ts"])) > MAX_GAP.total_seconds():
                raise invalid("Nicio cursă a liniei în jurul orei: nu putem lega check-in-ul de o cursă.", code="NO_TRIP")
    trip_id, day = str(chosen["trip_id"]), chosen["day"]
    st = f.stop_times[f.stop_times.trip_id == trip_id].sort_values("stop_sequence")
    stop_id = None
    if lat is not None and lon is not None:
        px = project_lonlats([(lon, lat)])[0]
        best = None
        for sid in st.stop_id.astype(str):
            xy = _stop_xy(sid)
            if xy is None:
                continue
            d = float(np.hypot(xy[0] - px[0], xy[1] - px[1]))
            if best is None or d < best[0]:
                best = (d, sid)
        stop_id = best[1] if best else None
    if stop_id is None and not st.empty:
        base = gtfs_service_start(day).timestamp()
        passed = st[base + st.dep_sec <= ts]
        stop_id = str((passed.iloc[-1] if not passed.empty else st.iloc[0]).stop_id)
    name = (load_network().stop_by_id.get(stop_id) or {}).get("name") if stop_id else None
    recs.sort(key=lambda r: r["start_ts"])
    i = next(k for k, r in enumerate(recs) if r["trip_id"] == trip_id)
    return {"tripStart": int(chosen["start_ts"]),
            "prevStart": int(recs[i - 1]["start_ts"]) if i > 0 else None,
            "nextStart": int(recs[i + 1]["start_ts"]) if i + 1 < len(recs) else None,
            "tripId": trip_id, "stopId": stop_id, "stopName": name, "method": method,
            "distanceToRouteMeters": None if dist_m is None else int(round(dist_m))}
