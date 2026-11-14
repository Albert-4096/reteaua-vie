"""R5: kilometres not run on the suspended section, and the walk between the cut ends.

Per (line, direction): the section of the GTFS shape between the first and the last lost stop (the line's
own end when the cut reaches it) × the trips in the window (departures at the first stop of the line's main
pattern, from the timetable in force before the works). The walk is the OSM pedestrian distance between the
last served stop before the cut and the first one after it. Km only, never money."""

from __future__ import annotations

import math
import re
import zipfile
from collections import Counter
from functools import lru_cache
from pathlib import Path

import pandas as pd
from shapely.geometry import LineString, Point

from app.common import gtfs, state
from app.common.city import load_network, route_mode
from app.common.errors import not_found
from app.common.geo import length_m, project_lonlats, to_metric
from app.common.timeutil import iso
from app.config import now
from app.m1_disruption import impact as imp
from app.m1_disruption.poster import WALK_METERS_PER_MIN
from app.models.base import I18n, Provenance
from app.common import provenance as prov

MODE_RO = {"tram": "Tramvai", "bus": "Autobuz", "trolleybus": "Troleibuz"}
MODE_EN = {"tram": "Tram", "bus": "Bus", "trolleybus": "Trolleybus"}


def _feed_zip(tt) -> Path:
    return tt.path if getattr(tt, "history", False) else gtfs.feed().path


@lru_cache(maxsize=4)
def _shapes(path_str: str, mtime: float) -> tuple[dict[tuple[str, int], str], dict[str, LineString]]:
    """({(route, dir): most used shape_id}, {shape_id: line in UTM metres}) of one GTFS zip."""
    with zipfile.ZipFile(path_str) as z:
        trips = pd.read_csv(z.open("trips.txt"), dtype=str, usecols=["route_id", "direction_id", "shape_id"]).fillna("")
        sh = pd.read_csv(z.open("shapes.txt"), dtype={"shape_id": str})
    trips["direction_id"] = trips["direction_id"].replace("", "0").astype(int)
    main: dict[tuple[str, int], str] = {}
    for (r, d), g in trips.groupby(["route_id", "direction_id"]):
        c = Counter(s for s in g["shape_id"] if s)
        if c:
            main[(r, int(d))] = c.most_common(1)[0][0]
    wanted = set(main.values())
    lines: dict[str, LineString] = {}
    sh = sh[sh["shape_id"].isin(wanted)].sort_values(["shape_id", "shape_pt_sequence"])
    for sid, g in sh.groupby("shape_id"):
        xy = project_lonlats(zip(g["shape_pt_lon"].astype(float), g["shape_pt_lat"].astype(float)))
        if len(xy) >= 2:
            lines[sid] = LineString(xy)
    return main, lines


def _shape(tt, route: str, direction: int) -> LineString | None:
    p = _feed_zip(tt)
    main, lines = _shapes(str(p), p.stat().st_mtime)
    sid = main.get((route, direction))
    return lines.get(sid) if sid else None


def _section(line: LineString, order: list[str], lost_idx: list[int]) -> tuple[float, float]:
    """(start, end) in metres along the shape of the lost stretch."""
    net = load_network()
    pos = []
    for i in lost_idx:
        s = net.stop_by_id.get(order[i])
        if s is not None:
            x, y = project_lonlats([tuple(s["location"])])[0]
            pos.append(line.project(Point(x, y)))
    if not pos:
        return 0.0, 0.0
    lo = 0.0 if 0 in lost_idx else min(pos)
    hi = line.length if (len(order) - 1) in lost_idx else max(pos)
    return lo, max(hi, lo)


def _name(stop_id: str) -> str:
    return (load_network().stop_by_id.get(stop_id) or {}).get("name", stop_id)


def km_report(closure_id: str) -> dict:
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    analysis = state.read("closures", closure_id, state.PART_ANALYSIS) if closure else None
    if closure is None or analysis is None:
        raise not_found(f"No analyzed closure {closure_id}.")
    from app.common.timeutil import parse_iso
    tt = imp.timetable_for_closure(closure)
    cw = imp.count_window(parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"]), tt)
    counts = imp.departure_counts(cw, tt)
    net = load_network()

    lost: dict[tuple[str, int], set[str]] = {}
    for row in analysis["stops"]:
        if imp.counts_as_lost(row):
            lost.setdefault((row["routeId"], int(row["directionId"])), set()).add(row["stopId"])

    lines, walks, skipped = [], [], []
    for (route, d), stops in sorted(lost.items()):
        order = tt.stop_order(route, d)
        idx = sorted(i for i, s in enumerate(order) if s in stops)
        short = (net.route_by_id.get(route) or {}).get("shortName", route)
        shape = _shape(tt, route, d)
        if not idx or shape is None:
            skipped.append(f"{short} sens {d}")
            continue
        lo, hi = _section(shape, order, idx)
        trips = counts.get((order[0], route, d)) if counts is not None else None
        sec_km = (hi - lo) / 1000.0
        mode = route_mode(route)
        lines.append({"routeId": route, "shortName": short, "mode": mode, "directionId": d,
                      "stopsLost": len(idx), "sectionKm": round(sec_km, 2), "trips": trips,
                      "kmNotRun": round(sec_km * trips, 1) if trips is not None else None})
        before = order[idx[0] - 1] if idx[0] > 0 else None
        after = order[idx[-1] + 1] if idx[-1] + 1 < len(order) else None
        if before and after:
            meters, exact = imp.walk_distance(before, after)
            minutes = max(1, math.ceil(meters / WALK_METERS_PER_MIN))
            walks.append({"routeId": route, "shortName": short, "directionId": d,
                          "fromStop": {"stopId": before, "name": _name(before)},
                          "toStop": {"stopId": after, "name": _name(after)},
                          "meters": int(round(meters / 10.0) * 10), "minutes": minutes, "approximate": not exact,
                          "sentence": I18n(
                              ro=f"Pe jos între {_name(before)} și {_name(after)}: {minutes} min" + ("" if exact else " (aproximativ)"),
                              en=f"On foot between {_name(before)} and {_name(after)}: {minutes} min" + ("" if exact else " (approximate)"))})

    by_mode: dict[str, dict] = {}
    for ln in lines:
        m = by_mode.setdefault(ln["mode"], {"mode": ln["mode"], "kmNotRun": 0.0, "trips": 0, "lines": [], "unknown": False})
        if ln["kmNotRun"] is None:
            m["unknown"] = True
        else:
            m["kmNotRun"] = round(m["kmNotRun"] + ln["kmNotRun"], 1)
            m["trips"] += ln["trips"]
        if ln["shortName"] not in m["lines"]:
            m["lines"].append(ln["shortName"])
    modes = [{"mode": m["mode"], "kmNotRun": None if m["unknown"] else m["kmNotRun"], "trips": m["trips"], "lines": m["lines"]}
             for m in by_mode.values()]
    temp = []
    for t in closure.get("temporaryRoutes") or []:
        g = t.get("geometry")
        km = round(length_m(LineString(g["coordinates"])) / 1000.0, 1) if g else None
        base_name = re.sub(r"[A-Za-z]+$", "", t["shortName"])      # 4b -> 4: the line it stands in for
        replaces = next((a["routeId"] for a in closure.get("routeActions") or []
                         if (net.route_by_id.get(a["routeId"]) or {}).get("shortName") == base_name), None)
        temp.append({"shortName": t["shortName"], "mode": t["mode"], "replacesRouteId": replaces, "geometryKm": km, "trips": None, "kmRun": None,
                     "note": I18n(ro="necunoscut: anunțul nu dă frecvența, deci nu putem număra cursele",
                                  en="unknown: the notice gives no frequency, so the trips cannot be counted")})
    row_text = _rows(lines, temp, walks)
    sources: list[Provenance] = [
        tt.provenance if getattr(tt, "history", False) else gtfs.feed().provenance,
        prov.provenance("Calcul Rețeaua Vie / our calculation", iso(now()), None, None,
                        "km nefăcuți = lungimea traseului GTFS între prima și ultima stație lipsă × cursele din fereastră "
                        "(plecări la prima stație a traseului principal); fără costuri, doar km; mers pe jos 80 m/min (4,8 km/h)"),
        net.provenance]
    if skipped:
        sources.append(prov.provenance("Linii lăsate în afara calculului", iso(now()), None, None,
                                        "stațiile lipsă nu sunt pe traseul principal din orar (variantă de traseu) sau linia nu are traseu GTFS: " + ", ".join(skipped)))
    return {"closureId": closure_id, "window": closure["window"], "timetableVersion": tt.version,
            "notRunByMode": modes, "lines": lines, "temporary": temp, "walkBetweenEnds": walks,
            "totalKmNotRun": None if any(m["kmNotRun"] is None for m in modes) or not modes else round(sum(m["kmNotRun"] for m in modes), 1),
            "rows": row_text, "provenance": sources}


def _rows(lines: list[dict], temp: list[dict], walks: list[dict]) -> list[dict]:
    """One text row per line: „Tramvai 4: <n> curse × <L> km nefăcuți · 4b: necunoscut · pe jos între capete: <m> min”."""
    out = []
    names = sorted({(ln["mode"], ln["shortName"]) for ln in lines})
    for mode, short in names:
        mine = [ln for ln in lines if ln["shortName"] == short and ln["mode"] == mode]
        trips = sum(ln["trips"] or 0 for ln in mine)
        km = sum(ln["kmNotRun"] or 0 for ln in mine)
        sec = max(ln["sectionKm"] for ln in mine)
        w = [x for x in walks if x["shortName"] == short]
        walk_ro = f" · pe jos între capete: {max(x['minutes'] for x in w)} min" if w else ""
        walk_en = f" · on foot between the ends: {max(x['minutes'] for x in w)} min" if w else ""
        mine_t = [t for t in temp if t["replacesRouteId"] in {ln["routeId"] for ln in mine}]
        tmp_ro = "".join(f" · {t['shortName']}: necunoscut" for t in mine_t)
        tmp_en = "".join(f" · {t['shortName']}: unknown" for t in mine_t)
        out.append({"mode": mode, "shortName": short, "kmNotRun": round(km, 1), "trips": trips,
                    "text": I18n(ro=f"{MODE_RO[mode]} {short}: {trips} curse × {sec:.1f} km nefăcuți (≈ {km:.0f} km){tmp_ro}{walk_ro}".replace(".", ","),
                                 en=f"{MODE_EN[mode]} {short}: {trips} trips × {sec:.1f} km not run (≈ {km:.0f} km){tmp_en}{walk_en}")})
    return out
