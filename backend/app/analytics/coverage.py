"""A10: residents per frequency class within walking distance of a stop, for the whole network.

For every GHSL cell (100 m, residents > 0): the departures per hour a resident can catch within
WALK_M (straight line, as in M4): per line, its best direction at the best stop in reach, summed over
lines, averaged over the window of a GTFS service day. Cells are summed per neighbourhood.
Reuses the M4/M1 population grid, zones and stop positions (`m1_disruption.impact`).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache

import numpy as np

from app.common import gtfs
from app.common import provenance as prov
from app.common.city import load_network, load_zones
from app.common.errors import ApiError
from app.config import TZ, now
from app.m1_disruption import impact
from app.models.base import I18n

WALK_M = 400
DAYS = ("weekday", "saturday", "sunday")
HOURS = (7, 19)

CLASSES = [
    ("none", "fără stație la 400 m", "no stop within 400 m", 0.0, 0.0),
    ("lt2", "sub 2 plecări pe oră", "under 2 departures an hour", 0.0, 2.0),
    ("2to4", "2–4 plecări pe oră", "2–4 departures an hour", 2.0, 4.0),
    ("4to8", "4–8 plecări pe oră", "4–8 departures an hour", 4.0, 8.0),
    ("ge8", "8 sau mai multe pe oră", "8 or more an hour", 8.0, None),
]
WEAK = ("none", "lt2")

METHOD = I18n(
    ro=("Locuitori din celule GHSL 2020 de 100 m (model, nu recensământ), pe clase de frecvență la cel mult "
        f"{WALK_M} m în linie dreaptă de o stație (aceeași rază ca M4). Frecvența unei celule = suma, peste liniile "
        "din rază, a plecărilor pe oră ale liniei (direcția și stația cu cele mai multe) în fereastra orară dintr-o zi "
        "de serviciu a orarului GTFS SMTT. „Acoperire slabă cu transport public” = sub 2 plecări pe oră sau nicio "
        "stație în rază. Distanța e în linie dreaptă, nu pe trotuar; orarul e planificat, nu observat."),
    en=("Residents of GHSL 2020 100 m cells (a model, not a census), by frequency class within "
        f"{WALK_M} m straight-line of a stop (same radius as M4). A cell's frequency = sum over the lines in reach "
        "of the line's departures per hour (best direction, best stop) in the hour window of one GTFS service day. "
        "Weak coverage = under 2 departures an hour or no stop in reach. Straight-line distance, planned timetable."))
CAVEAT = I18n(
    ro=("Descriem acoperirea cu transport public a unei zone, nu oamenii din ea. Locuitorii sunt estimați din "
        "grila GHSL (nu recensământ); orarul e cel planificat în GTFS, nu cel observat."),
    en=("This describes how well public transport covers an area, not the people in it. Residents come from the "
        "GHSL grid (not a census); the timetable is the planned GTFS one, not the observed one."))


def reference_date(day: str) -> date:
    """The first service day on or after the app clock of the requested kind that has departures."""
    first, last = gtfs.coverage()
    d = max(now().astimezone(TZ).date(), first)
    want = {"weekday": range(0, 5), "saturday": (5,), "sunday": (6,)}[day]
    for _ in range(60):
        if d > last:
            break
        if d.weekday() in want:
            s = datetime(d.year, d.month, d.day, 7, tzinfo=TZ)
            if gtfs.count_departures(s, s + timedelta(hours=1)) > 0:
                return d
        d += timedelta(days=1)
    raise ApiError(422, "OUTSIDE_FEED", f"No {day} service day with departures in the feed (to {last}).")


def _classify(f: np.ndarray, near: np.ndarray) -> np.ndarray:
    cls = np.full(len(f), 4, dtype=np.int8)
    cls[f < 8] = 3
    cls[f < 4] = 2
    cls[f < 2] = 1
    cls[~near] = 0
    return cls


@lru_cache(maxsize=8)
def _cells(feed_sha: str, d: date, h0: int, h1: int):
    """(frequency per cell, has a stop in reach per cell); the grid is impact.pop_grid()."""
    grid = impact.pop_grid()
    if grid is None:
        raise ApiError(503, "UNAVAILABLE", "The GHSL population grid is missing (în lucru).")
    net = load_network()
    start = datetime(d.year, d.month, d.day, h0, tzinfo=TZ)
    end = datetime(d.year, d.month, d.day, h1, tzinfo=TZ)
    counts = gtfs.count_by_key(start, end)
    idx = {s: i for i, s in enumerate(net.stop_ids)}
    routes = sorted({r for (_s, r, _d) in counts})
    ri = {r: i for i, r in enumerate(routes)}
    per_h = np.zeros((len(net.stop_ids), len(routes)))
    for (s, r, _dir), n in counts.items():
        if s in idx:
            per_h[idx[s], ri[r]] = max(per_h[idx[s], ri[r]], n / (h1 - h0))  # best direction at this stop
    served = per_h.sum(axis=1) > 0
    sxy = net.stop_xy[served]
    sf = per_h[served]
    freq = np.zeros(len(grid.xy))
    near = np.zeros(len(grid.xy), dtype=bool)
    for lo in range(0, len(grid.xy), 2000):
        c = grid.xy[lo:lo + 2000]
        within = np.hypot(c[:, None, 0] - sxy[None, :, 0], c[:, None, 1] - sxy[None, :, 1]) <= WALK_M
        for i in range(len(c)):
            m = within[i]
            if m.any():
                near[lo + i] = True
                freq[lo + i] = sf[m].max(axis=0).sum()
    return freq, near


def _zone_row(slug: str, name: str, res: np.ndarray, cls: np.ndarray, freq: np.ndarray) -> dict:
    total = float(res.sum())
    by = [int(round(float(res[cls == k].sum()))) for k in range(len(CLASSES))]
    weak = int(round(float(res[cls <= 1].sum())))
    med = None
    if total > 0:
        o = np.argsort(freq)
        cum = np.cumsum(res[o])
        med = round(float(freq[o][np.searchsorted(cum, total / 2)]), 1)
    return {"slug": slug, "name": name, "residents": int(round(total)), "byClass": by, "weakResidents": weak,
            "weakShare": round(weak / total, 3) if total else None, "medianPerHour": med, "rank": None}


def summary(day: str = "weekday", h0: int = HOURS[0], h1: int = HOURS[1]) -> dict:
    if day not in DAYS:
        raise ApiError(422, "INVALID_INPUT", f"`day` must be one of {', '.join(DAYS)}.")
    if not (0 <= h0 < h1 <= 24):
        raise ApiError(422, "INVALID_INPUT", "`from` and `to` must be hours with 0 <= from < to <= 24.")
    d = reference_date(day)
    f = gtfs.feed(d)
    freq, near = _cells(f.sha256, d, h0, h1)
    grid = impact.pop_grid()
    cls = _classify(freq, near)
    zones = load_zones()
    rows = []
    for i, slug in enumerate(zones.slugs):
        m = grid.zone == i
        if m.any():
            rows.append(_zone_row(slug, zones.names.get(slug, slug), grid.residents[m], cls[m], freq[m]))
    out = grid.zone < 0
    outside = _zone_row(impact.OUTSIDE_SLUG, impact.OUTSIDE_NAME, grid.residents[out], cls[out], freq[out]) if out.any() else None
    rows.sort(key=lambda r: -r["weakResidents"])
    for k, r in enumerate(rows, 1):
        r["rank"] = k
    if outside:
        rows.append(outside)
    city = _zone_row("_city", "Toată grila GHSL / whole GHSL grid", grid.residents, cls, freq)
    provs = [f.provenance, impact.pop_provenance(), zones.provenance]
    return {"day": day, "date": d.isoformat(), "hours": [h0, h1], "walkMeters": WALK_M,
            "classes": [{"id": c[0], "label": {"ro": c[1], "en": c[2]}, "minPerHour": c[3], "maxPerHour": c[4]}
                        for c in CLASSES],
            "city": city, "zones": rows, "method": METHOD.model_dump(), "caveat": CAVEAT.model_dump(),
            "provenance": [p.model_dump() for p in provs]}


def layer(day: str = "weekday", h0: int = HOURS[0], h1: int = HOURS[1]) -> dict:
    """Zone polygons with their coverage, for a choropleth."""
    s = summary(day, h0, h1)
    by = {z["slug"]: z for z in s["zones"]}
    feats = []
    for ft in load_zones().collection["features"]:
        slug = ft["properties"]["slug"]
        z = by.get(slug)
        feats.append({"type": "Feature", "geometry": ft["geometry"],
                      "properties": {"slug": slug, "name": ft["properties"]["name"],
                                     "residents": z["residents"] if z else None,
                                     "weakResidents": z["weakResidents"] if z else None,
                                     "weakShare": z["weakShare"] if z else None,
                                     "rank": z["rank"] if z else None}})
    return {"type": "FeatureCollection", "layer": "coverage", "features": feats, "provenance": s["provenance"]}
