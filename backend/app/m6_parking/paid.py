"""R11: paid parking in the works window, measured from the City Hall's own Timpark file.

The Timpark streets and car parks M6 already finds (`parking.features_in`) get:
- metres of paid street inside the closure buffer, and m² of each car park that touches it;
- the paid hours inside the window per tariff colour, from the schedule in the same file
  (`tariffs.schedule`: weekdays 08-20, Saturday only green 08-17, Sunday none), local time;
- the nearest Park & Ride whose line still runs (M6 `options_for`).
No lei and no occupancy (the file's tariff field is named `eur`, and Timpark publishes no
occupancy). Public holidays are not in the schedule, so they are not subtracted. Whether to
suspend payment is Timpark's decision.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta

from shapely.geometry import shape

from app.common import gtfs
from app.common.city import _city_file, _read_json, load_network, load_parking
from app.common.geo import from_geojson, project_lonlats, to_metric
from app.common.timeutil import iso, parse_iso
from app.config import TZ
from app.m6_parking import parking as pk
from app.models.base import I18n, Window
from app.models.v2 import PaidMeasure, PaidParking, ParkAndRide

COLOURS = ("green", "red", "yellow", "blue")


def _intervals(start: datetime, end: datetime, colour: str, schedule: dict) -> list[tuple[datetime, datetime]]:
    out = []
    day = start.astimezone(TZ).date()
    while datetime(day.year, day.month, day.day, tzinfo=TZ) < end:
        wd = day.weekday()
        span = None
        if wd < 5:
            span = schedule.get("weekdays")
        elif wd == 5:
            span = (schedule.get("saturday") or {}).get(colour)
        if span:
            a = datetime(day.year, day.month, day.day, int(span[0]), tzinfo=TZ)
            b = datetime(day.year, day.month, day.day, int(span[1]), tzinfo=TZ)
            a, b = max(a, start), min(b, end)
            if a < b:
                out.append((a, b))
        day += timedelta(days=1)
    return out


def _hours(iv: list[tuple[datetime, datetime]]) -> float:
    return round(sum((b - a).total_seconds() for a, b in iv) / 3600, 1)


def _union(ivs: list[list[tuple[datetime, datetime]]]) -> list[tuple[datetime, datetime]]:
    flat = sorted(x for iv in ivs for x in iv)
    out: list[tuple[datetime, datetime]] = []
    for a, b in flat:
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _measure(items: list[dict], kind: str) -> PaidMeasure:
    by: dict[str, int] = {}
    for it in items:
        by[it["tariff"]] = by.get(it["tariff"], 0) + it["value"]
    total = sum(by.values())
    return PaidMeasure(count=len(items), meters=total if kind == "street" else None,
                       squareMeters=total if kind == "lot" else None, byTariff=dict(sorted(by.items())))


def _features(closure: dict) -> tuple[list[dict], list[dict]]:
    """(streets, lots) touching the closure buffer: {id, name, tariff, value (m inside the buffer, or m²), checked}."""
    buf = pk.closure_buffer(closure)
    streets, lots = pk.features_in(buf)
    checked = {f["id"]: bool(f.get("checked")) for f in _read_json(_city_file("parking.json"))["features"]}
    s_out = [{"id": r.id, "name": r.name, "tariff": r.tariff, "checked": checked.get(r.id, False),
              "value": int(round(to_metric(shape(r.geometry).intersection(buf)).length))} for r in streets]
    l_out = [{"id": r.id, "name": r.name, "tariff": r.tariff, "checked": checked.get(r.id, False),
              "value": int(round(to_metric(shape(r.geometry)).area))} for r in lots]
    return s_out, l_out


def _window(closure: dict, start: str | None, end: str | None) -> tuple[datetime, datetime]:
    s = parse_iso(start) if start else parse_iso(closure["window"]["start"])
    e = parse_iso(end) if end else parse_iso(closure["window"]["end"])
    if e <= s:
        from app.common.errors import invalid
        raise invalid("`end` must be after `start`.")
    return s, e


def _nearest_pr(closure: dict, options: list[ParkAndRide]) -> ParkAndRide | None:
    if not options:
        return None
    f = gtfs.feed()
    xy = dict(zip(f.stops.stop_id.astype(str), project_lonlats(zip(f.stops.stop_lon.astype(float), f.stops.stop_lat.astype(float)))))
    from shapely.geometry import Point
    line = to_metric(from_geojson(closure["geometry"]))
    return min(options, key=lambda o: (line.distance(Point(*xy[o.stopId])) if o.stopId in xy else 1e9, o.stopId))


def _short(route_ids: list[str]) -> str:
    by = load_network().route_by_id
    return ", ".join(by.get(r, {}).get("shortName", r) for r in route_ids)


def notice_sentence(closure: dict, analysis: dict | None, area) -> tuple[str, str] | None:
    """The sentence for a zone notice: closed paid streets inside `area` (WGS84) and the nearest P&R. None if nothing."""
    streets, _lots = pk.features_in(area.intersection(pk.closure_buffer(closure)) if area is not None else pk.closure_buffer(closure))
    if not streets:
        return None  # the P&R line goes with closed paid streets, not on every notice
    pr = _nearest_pr(closure, pk.options_for(closure, analysis))
    ro, en = [], []
    if streets:
        names = list(dict.fromkeys(s.name for s in streets if s.name))[:3]
        ro.append("Parcare cu plată afectată: " + (", ".join(names) if names else f"{len(streets)} tronsoane Timpark") + ".")
        en.append("Paid parking affected: " + (", ".join(names) if names else f"{len(streets)} Timpark sections") + ".")
    if pr is not None:
        walk = f", parcare Timpark la {int(round(pr.walkMeters))} m" if pr.walkMeters is not None else ""
        walk_en = f", Timpark car park {int(round(pr.walkMeters))} m away" if pr.walkMeters is not None else ""
        ro.append(f"Parcare și mergi cu transportul în comun: stația {pr.name}, linia {_short(pr.routeIds)}{walk}.")
        en.append(f"Park and ride: stop {pr.name}, line {_short(pr.routeIds)}{walk_en}.")
    return " ".join(ro), " ".join(en)


def paid_parking(closure_id: str, start: str | None = None, end: str | None = None) -> PaidParking:
    closure = pk.load_closure(closure_id)
    s, e = _window(closure, start, end)
    pd = load_parking()
    schedule = (pd.tariffs or {}).get("schedule") or {}
    streets, lots = _features(closure)
    present = sorted({x["tariff"] for x in streets + lots}, key=lambda c: COLOURS.index(c) if c in COLOURS else 9)
    ivs = {c: _intervals(s, e, c, schedule) for c in present}
    by_hours = {c: _hours(iv) for c, iv in ivs.items()}
    total_h = _hours(_union(list(ivs.values())))
    unchecked = sum(1 for x in streets + lots if not x["checked"])
    options = pk.options_for(closure, pk._analysis(closure_id))
    sm, lm = _measure(streets, "street"), _measure(lots, "lot")
    if not streets and not lots:
        ro, en = ("Nicio stradă sau parcare Timpark în zona afectată.", "No Timpark street or car park in the affected area.")
    else:
        ro = (f"Parcare cu plată afectată: {sm.meters} m de stradă, {lm.count} "
              f"{'parcare' if lm.count == 1 else 'parcări'} · {total_h:g} ore plătite în fereastră.")
        en = (f"Paid parking affected: {sm.meters} m of street, {lm.count} car park{'' if lm.count == 1 else 's'} · "
              f"{total_h:g} paid hours in the window.")
    note = I18n(
        ro=("Metri de stradă = lungimea tronsoanelor Timpark din zona afectată; m² = suprafața întreagă a parcării care atinge zona. "
            "Orele plătite vin din programul oficial din fișierul Primăriei (L–V 08–20, sâmbătă doar verde 08–17, duminică 0); "
            "sărbătorile legale nu sunt în program și nu sunt scăzute. Fără lei (câmpul Primăriei se numește `eur`) și fără ocupare: "
            "Timpark nu le publică. Dacă se suspendă plata e decizia Timpark."),
        en=("Metres = length of the Timpark sections in the affected area; m² = whole area of each car park that touches it. "
            "Paid hours come from the schedule in the City Hall file (Mon-Fri 08-20, Saturday green only 08-17, Sunday 0); public "
            "holidays are not in it and are not subtracted. No currency (the City Hall field is named `eur`) and no occupancy: "
            "Timpark publishes neither. Suspending payment is Timpark's decision."))
    return PaidParking(closureId=closure_id, window=Window(start=iso(s), end=iso(e)), streets=sm, lots=lm,
                       paidHours=total_h, paidHoursByTariff=by_hours, uncheckedFeatures=unchecked, parkAndRide=options,
                       noticeLine=I18n(ro=ro, en=en), note=note, provenance=pk.provenance_list(with_pr=True))


def to_csv(closure_id: str, start: str | None = None, end: str | None = None) -> str:
    closure = pk.load_closure(closure_id)
    s, e = _window(closure, start, end)
    schedule = (load_parking().tariffs or {}).get("schedule") or {}
    streets, lots = _features(closure)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["id", "tip", "nume", "culoare tarif", "metri de stradă în zonă", "m² parcare", "început fereastră",
                "sfârșit fereastră", "ore plătite în fereastră", "marcat verificat de Primărie"])
    for kind, items in (("stradă", streets), ("parcare", lots)):
        for x in items:
            h = _hours(_intervals(s, e, x["tariff"], schedule))
            w.writerow([x["id"], kind, x["name"], x["tariff"], x["value"] if kind == "stradă" else "",
                        x["value"] if kind == "parcare" else "", iso(s), iso(e), h, "da" if x["checked"] else "nu"])
    return "﻿" + buf.getvalue()
