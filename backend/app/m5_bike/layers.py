"""The `bike` map layer (CONTRACT LayerCollection, GET /api/layers/bike?bbox=).

Features: bike infrastructure ways as `lane` (cycleway, track, designated path, painted lane;
`lts` per way from app.m5_bike.lts), bike parking as `parking` and bike-share stations as
`share_station` (points, `lts` null). The city-wide layer is built once and kept in memory;
a bbox only filters it.
"""

from __future__ import annotations

from functools import lru_cache

from shapely.geometry import LineString, Point, box
from shapely.ops import linemerge

from app.common.geo import to_geojson
from app.m1_disruption.impact import osm_provenance
from app.m5_bike.osm_bike import bike_data

Bbox = tuple[float, float, float, float]


@lru_cache(maxsize=1)
def _features() -> tuple[list[dict], list]:
    """[(feature dict)] and their WGS84 shapes, city-wide."""
    d = bike_data()
    by_way: dict[int, list[int]] = {}
    for i, w in enumerate(d.seg_way.tolist()):
        if d.way_bike[w]:
            by_way.setdefault(w, []).append(i)
    feats, shapes = [], []
    for w in sorted(by_way, key=lambda w: int(d.way_id[w])):
        merged = linemerge([LineString(d.seg_coords[i]) for i in by_way[w]])
        parts = [merged] if merged.geom_type == "LineString" else list(merged.geoms)
        for part in parts:
            feats.append({"type": "Feature", "geometry": to_geojson(part),
                          "properties": {"kind": "lane", "osmId": f"way/{int(d.way_id[w])}",
                                         "name": d.way_name[w], "lts": d.way_lts[w]}})
            shapes.append(part)
    for k, (lon, lat) in enumerate(d.poi_lonlat.tolist()):
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]},
                      "properties": {"kind": d.poi_kind[k], "osmId": d.poi_osm[k], "name": d.poi_name[k],
                                     "lts": None}})
        shapes.append(Point(lon, lat))
    return feats, shapes


def bike_layer(bbox: Bbox | None = None) -> dict:
    feats, shapes = _features()
    if bbox is not None:
        area = box(*bbox)
        feats = [f for f, s in zip(feats, shapes) if s.intersects(area)]
    lanes = sum(1 for f in feats if f["properties"]["kind"] == "lane")
    note = (f"{lanes} tronsoane de infrastructură pentru biciclete, nivel de stres LTS din etichetele OSM "
            f"(tabelul din README); lipsa din OSM = necunoscut / bike ways with LTS from OSM tags; "
            f"missing in OSM = unknown")
    return {"type": "FeatureCollection", "layer": "bike", "features": feats,
            "provenance": [osm_provenance(note).model_dump()]}
