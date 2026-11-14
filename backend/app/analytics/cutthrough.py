"""R23: the detour streets of a closure that are neighbourhood streets, with the residents along them.

Calls `app.m4_access.detour` (the Braess F1 edge-betweenness detour load); it only adds, per detour edge:
the OSM road class of the street, the GHSL residents within RESIDENT_M and, as supporting evidence only, the
vehicle-minutes the L4 cells record within STANDING_M of it. `roadClass` comes from the OSM `highway` tag of the
drive ways the edge runs on (the most common, by length). Neighbourhood street = residential or living_street.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from functools import lru_cache

import numpy as np
from shapely.geometry import LineString
from shapely.strtree import STRtree

from app.analytics import streets
from app.common import state
from app.common import provenance as prov
from app.common.errors import not_found
from app.common.geo import to_metric
from app.config import get_settings
from app.m1_disruption import impact
from app.m4_access import detour
from app.models.base import I18n

RESIDENT_M = 50.0
STANDING_M = 60.0
MATCH_M = 4.0
NEIGHBOURHOOD = ("residential", "living_street")

LABEL = I18n(ro="Structura rețelei, nu volume de trafic: străzile care preiau ocolirea dacă mașinile aleg drumul cel mai scurt.",
             en="Network structure, not traffic volumes.")
COMMISSION = I18n(ro="Propunere: acces riverani + semnalizarea ocolirii oficiale. Decizia aparține Primăriei și poliției rutiere.",
                  en="Proposal: residents-only access + signs for the official detour. The decision is the City Hall's.")
METHOD = I18n(
    ro=("Străzile din lista de ocolire (sarcina structurală, M4). Clasă de drum = eticheta OSM highway a drumurilor pe care "
        f"merge strada (cea mai frecventă, după lungime); „stradă de cartier” = residential sau living_street. Locuitori = "
        f"celule GHSL 2020 de 100 m (model, nu recensământ) la cel mult {RESIDENT_M:.0f} m. Minute de stat pe loc (L4) "
        f"la cel mult {STANDING_M:.0f} m: doar date de sprijin, din primele 300 de celule, nu dovadă de trafic de tranzit."),
    en="Detour list from M4; OSM highway class; GHSL residents within 50 m; L4 standing minutes as supporting evidence only.")


def _highway_map_path():
    pbf = detour._pbf()
    st = pbf.stat()
    key = hashlib.sha1(f"1:{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()[:12]
    return get_settings().cache_dir / f"osm_way_highway_v1_{key}.json"


@lru_cache(maxsize=1)
def way_highway() -> dict[int, str]:
    p = _highway_map_path()
    if p.is_file():
        return {int(k): v for k, v in json.loads(p.read_text(encoding="utf-8")).items()}
    from pyrosm import OSM

    _n, edges = OSM(str(detour._pbf())).get_network(network_type="driving", nodes=True)
    out = {int(i): str(h) for i, h in zip(edges["id"], edges["highway"]) if isinstance(h, str)}
    p.write_text(json.dumps(out), encoding="utf-8")
    return out


@lru_cache(maxsize=1)
def _seg_metric() -> tuple[STRtree, list[LineString]]:
    d = detour.drive_edges()
    lines = [LineString(x) for x in d.xy]
    return STRtree(lines), lines


def road_class(line_metric: LineString) -> str | None:
    tree, lines = _seg_metric()
    d = detour.drive_edges()
    hw = way_highway()
    zone = line_metric.buffer(MATCH_M)
    weight: Counter = Counter()
    for i in tree.query(zone, predicate="intersects"):
        h = hw.get(int(d.way[i]))
        if h:
            weight[h] += lines[i].intersection(zone).length
    return weight.most_common(1)[0][0] if weight else None


def residents_along(line_metric: LineString) -> int:
    grid = impact.pop_grid()
    if grid is None:
        return 0
    minx, miny, maxx, maxy = line_metric.bounds
    m = (grid.xy[:, 0] >= minx - RESIDENT_M) & (grid.xy[:, 0] <= maxx + RESIDENT_M) \
        & (grid.xy[:, 1] >= miny - RESIDENT_M) & (grid.xy[:, 1] <= maxy + RESIDENT_M)
    idx = np.nonzero(m)[0]
    if not len(idx):
        return 0
    from shapely import points

    pts = points(grid.xy[idx])
    near = np.array([line_metric.distance(p) <= RESIDENT_M for p in pts])
    return int(round(float(grid.residents[idx][near].sum())))


def _standing_cells() -> tuple[list, dict]:
    try:
        s = streets.standing()
    except RuntimeError:
        return [], {}
    from app.common.geo import lonlat_to_xy

    pts = [(lonlat_to_xy(*p["location"]), p["minutes"]) for p in s["points"]]
    return pts, s["recording"]


def build(closure_id: str) -> "CutThrough":  # noqa: F821 - model imported lazily below
    from app.analytics.models import CutThrough

    load = detour.cached_for(closure_id) or detour.compute_for(closure_id)
    names = {r.route_id: (r.route_short_name or r.route_id) for r in __import__("app.common.gtfs", fromlist=["x"]).feed().routes.itertuples(index=False)}
    cells, rec = _standing_cells()
    label = (rec.get("label") or {}).get("ro") if rec else None
    out = []
    for k, e in enumerate(load.edges, 1):
        line = to_metric(LineString(e.geometry.coordinates))
        hw = road_class(line)
        ev = None
        if cells and label:
            near = [(m) for (xy, m) in cells if line.distance(__import__("shapely.geometry", fromlist=["Point"]).Point(xy)) <= STANDING_M]
            if near:
                ev = {"minutes": round(float(sum(near)), 1), "cells": len(near),
                      "label": {"ro": f"{label}; date de sprijin, nu dovadă de trafic de tranzit",
                                "en": "supporting evidence only, from the recording"}}
        out.append({"rank": k, "name": e.name, "roadClass": hw, "neighbourhood": hw in NEIGHBOURHOOD,
                    "residentsAlong": residents_along(line), "lines": [names.get(r, r) for r in e.routeIdsOnEdge],
                    "changePct": e.changePct, "geometry": dict(e.geometry.model_dump()), "standing": ev})
    hood = [s for s in out if s["neighbourhood"]]
    provs = [*load.provenance, impact.pop_provenance(), prov.for_file("OpenStreetMap", detour._pbf(), "https://www.openstreetmap.org", None,
                                                                        "highway tag of the drive ways")]
    return CutThrough(closureId=closure_id, streets=out, neighbourhoodStreets=len(hood),
                      residentsAlongNeighbourhood=int(sum(s["residentsAlong"] for s in hood)), label=LABEL,
                      commission=COMMISSION, method=METHOD, provenance=provs)


def job_key(closure_id: str) -> str:
    from app.common import jobs

    return f"cut-through:v1:{closure_id}:{jobs.closure_fingerprint(closure_id)}"


def closure_or_404(closure_id: str) -> dict:
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id}.")
    return closure
