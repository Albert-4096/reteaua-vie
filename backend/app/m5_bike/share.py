"""R17: bike-share stations as the alternative to a suspended section.

For each suspended section (the first and the last stop of a line and direction that lose
service, in the GTFS stop order) the nearest OSM `bicycle_rental` station within 400 m of each
end, and the M5 LTS route between the two stations that avoids the closed section. Availability
is unknown (no live feed): the line says so. Distances to the stations are straight-line.
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString

from app.common import gtfs
from app.common.geo import project_lonlats
from app.models.base import I18n
from app.models.v2 import ShareAlternative, ShareStation

MAX_STATION_M = 400.0
MAX_SECTIONS = 4
MAX_ROUTE_STRAIGHT_M = 3000.0   # a longer section is not a bike alternative, and routing it is slow
NONE_LINE = I18n(ro="Nicio stație de bicicletă publică la mai puțin de 400 m de capetele secțiunii.",
                 en="No public bike station within 400 m of the section's ends.")


def sections(analysis: dict | None) -> list[dict]:
    """[{fromStopId, fromStopName, toStopId, toStopName, from_xy, to_xy, routeIds}] from the lost rows, most lines first."""
    from app.m1_disruption.impact import counts_as_lost

    by_dir: dict[tuple[str, int], dict[str, dict]] = {}
    for r in (analysis or {}).get("stops") or []:
        if counts_as_lost(r) and r.get("location"):
            by_dir.setdefault((r["routeId"], int(r.get("directionId") or 0)), {})[str(r["stopId"])] = r
    out: dict[tuple[str, str], dict] = {}
    for (route, direction), rows in by_dir.items():
        order = [s for s in gtfs.stop_order(route, direction) if s in rows] or list(rows)
        a, b = rows[order[0]], rows[order[-1]]
        key = (str(a["stopId"]), str(b["stopId"]))
        sec = out.setdefault(key, {"fromStopId": key[0], "fromStopName": a.get("name") or key[0], "toStopId": key[1],
                                   "toStopName": b.get("name") or key[1], "from_lonlat": a["location"][:2],
                                   "to_lonlat": b["location"][:2], "routeIds": set()})
        sec["routeIds"].add(route)
    secs = sorted(out.values(), key=lambda s: (-len(s["routeIds"]), s["fromStopId"], s["toStopId"]))[:MAX_SECTIONS]
    for s in secs:
        s["routeIds"] = sorted(s["routeIds"])
    return secs


def _nearest_station(d, lonlat) -> tuple[int, float] | None:
    idx = [i for i, k in enumerate(d.poi_kind) if k == "share_station"]
    if not idx:
        return None
    xy = project_lonlats(d.poi_lonlat[idx])
    p = project_lonlats([tuple(lonlat)])[0]
    dist = np.hypot(xy[:, 0] - p[0], xy[:, 1] - p[1])
    k = int(np.argmin(dist))
    return (idx[k], float(dist[k])) if dist[k] <= MAX_STATION_M else None


def share_alternatives(d, c, analysis: dict | None, detour_route, edge_summary) -> tuple[list[ShareAlternative], I18n | None]:
    """`detour_route(d, closure_like, [])` and `edge_summary(route) -> (length_m, high_stress_m)` come from bike.py."""
    secs = sections(analysis)
    rows: list[ShareAlternative] = []
    for s in secs:
        ns_a, ns_b = _nearest_station(d, s["from_lonlat"]), _nearest_station(d, s["to_lonlat"])

        def station(hit):
            if hit is None:
                return None
            i, m = hit
            return ShareStation(osmId=d.poi_osm[i], name=d.poi_name[i], meters=int(round(m)))

        length = high = None
        line = None
        pa = pb = None
        if ns_a and ns_b and ns_a[0] != ns_b[0]:
            pa = project_lonlats([tuple(d.poi_lonlat[ns_a[0]])])[0]
            pb = project_lonlats([tuple(d.poi_lonlat[ns_b[0]])])[0]
            if float(np.hypot(*(pa - pb))) > MAX_ROUTE_STRAIGHT_M:
                pa = pb = None
        if pa is not None:
            route = detour_route(d, type(c)(LineString([tuple(pa), tuple(pb)]), c.buf), [])
            if route is not None:
                length, high = edge_summary(route)
                na = d.poi_name[ns_a[0]] or "stație fără nume în OSM"
                nb = d.poi_name[ns_b[0]] or "stație fără nume în OSM"
                na_en = d.poi_name[ns_a[0]] or "station unnamed in OSM"
                nb_en = d.poi_name[ns_b[0]] or "station unnamed in OSM"
                km = f"{length / 1000:.1f}".replace(".", ",")
                line = I18n(ro=f"Alternativ: bicicletă publică de la {na} la {nb}, {km} km · disponibilitate necunoscută.",
                            en=f"Alternative: public bike from {na_en} to {nb_en}, {length / 1000:.1f} km · availability unknown.")
        rows.append(ShareAlternative(fromStopId=s["fromStopId"], fromStopName=s["fromStopName"], toStopId=s["toStopId"],
                                     toStopName=s["toStopName"], routeIds=s["routeIds"], stationFrom=station(ns_a),
                                     stationTo=station(ns_b), routeLengthMeters=None if length is None else round(length, 1),
                                     highStressMeters=None if high is None else round(high, 1), line=line))
    note = None if any(r.line for r in rows) else NONE_LINE
    return rows, note
