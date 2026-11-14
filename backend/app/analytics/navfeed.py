"""R23: two plain, documented files of every published closure for navigation apps.

waze-cifs.json   incidents shaped after Waze's Closure and Incident Feed Specification (CIFS): id, type, subtype,
                 street, polyline ("lat lon lat lon ..."), starttime, endtime, description, direction, source.
                 We read the public spec; we do not know that Timișoara is a Waze for Cities partner, and we do not
                 claim that any app reads this file („pot citi”, de verificat).
avoid-streets    GeoJSON: each closure, and the neighbourhood streets of its detour list (cut-through risk) that a
                 navigation app is advised to keep out of, with the official detour streets as text.
"""

from __future__ import annotations

from datetime import datetime

from app.analytics import cutthrough
from app.common import jobs
from app.common.geo import from_geojson
from app.common.timeutil import iso, parse_iso
from app.m7_compliance.datex import published_closures

FIELDS = {
    "incidents[].id": "closure id",
    "incidents[].type": "ROAD_CLOSED (CIFS type)",
    "incidents[].subtype": "ROAD_CLOSED_CONSTRUCTION (works) or ROAD_CLOSED_EVENT",
    "incidents[].street": "the closure title (the notice names the streets)",
    "incidents[].polyline": "WGS84 'lat lon lat lon ...' of one line of the closure geometry",
    "incidents[].starttime / endtime": "ISO 8601 with offset, the closure window",
    "incidents[].description": "title + the official detour streets",
    "incidents[].direction": "BOTH_DIRECTIONS",
    "incidents[].source": "{ reference: closure id, name: 'Rețeaua Vie (demo)', url: the STPT notice }",
}
LABEL_RO = "pot citi: format după specificația CIFS, de verificat; nu știm ca vreo aplicație să-l consume"


def _lines(geometry: dict | None) -> list[list[tuple[float, float]]]:
    if not geometry:
        return []
    g = from_geojson(geometry)
    parts = list(getattr(g, "geoms", [g]))
    return [[(float(c[0]), float(c[1])) for c in p.coords] for p in parts if p.geom_type == "LineString" and len(p.coords) >= 2]


def detour_text(closure: dict) -> str:
    bits = []
    for t in closure.get("temporaryRoutes") or []:
        if t.get("streets"):
            bits.append(f"linia {t['shortName']}: " + " → ".join(t["streets"]))
    return "Ocolire oficială: " + "; ".join(bits) if bits else ""


def cifs() -> tuple[dict, list[str]]:
    incidents, notes = [], []
    for pc in published_closures(active_only=False):
        c = pc.closure
        lines = _lines(c.get("geometry"))
        if not lines:
            notes.append(f"{c['id']}: no line geometry, left out")
            continue
        title = (c.get("title") or {}).get("ro", c["id"])
        desc = " ".join(x for x in (title, detour_text(c)) if x)
        subtype = "ROAD_CLOSED_EVENT" if "event" in (c.get("kind") or "") else "ROAD_CLOSED_CONSTRUCTION"
        street = title
        for k, line in enumerate(lines):
            incidents.append({
                "id": c["id"] if len(lines) == 1 else f"{c['id']}_{k + 1}",
                "type": "ROAD_CLOSED", "subtype": subtype, "street": street,
                "polyline": " ".join(f"{lat:.6f} {lon:.6f}" for lon, lat in line),
                "starttime": c["window"]["start"], "endtime": c["window"]["end"],
                "description": desc[:500], "direction": "BOTH_DIRECTIONS",
                "creationtime": pc.published_at, "updatetime": pc.published_at,
                "source": {"reference": c["id"], "name": "Rețeaua Vie (demo)", "url": c.get("sourceUrl")}})
    return {"incidents": incidents}, notes


def avoid_streets() -> tuple[dict, list[str]]:
    feats, notes = [], []
    for pc in published_closures(active_only=False):
        c = pc.closure
        for line in _lines(c.get("geometry")):
            feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [list(p) for p in line]},
                          "properties": {"kind": "closure", "closureId": c["id"], "title": (c.get("title") or {}).get("ro"),
                                         "start": c["window"]["start"], "end": c["window"]["end"],
                                         "officialDetour": detour_text(c) or None}})
        ct = jobs.cached(cutthrough.job_key(c["id"]))
        if ct is None:
            notes.append(f"{c['id']}: cut-through analysis not computed yet (in lucru), no avoid-streets")
            continue
        for s in ct.streets:
            if s.neighbourhood:
                feats.append({"type": "Feature", "geometry": s.geometry,
                              "properties": {"kind": "avoid", "closureId": c["id"], "name": s.name, "roadClass": s.roadClass,
                                             "residentsAlong": s.residentsAlong,
                                             "reason": "stradă de cartier pe lista de ocolire (structură de rețea, nu trafic măsurat)"}})
    doc = {"kind": "Feature properties: closure {closureId,title,start,end,officialDetour}; avoid {closureId,name,"
                   "roadClass,residentsAlong,reason}. Coordinates [lon, lat] (RFC 7946).", "label": LABEL_RO}
    return {"type": "FeatureCollection", "features": feats, "properties": doc}, notes
