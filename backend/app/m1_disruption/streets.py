"""R1-B: find a street in the City Hall's register and cut the section a person closes on the map.

Search reads the register file the parser already uses ($DATA_DIR/city-api-*/nomenclator-strazi.json:
name, codGis, type, neighbourhood, former name). The geometry is the street's OpenStreetMap ways
from our extract (parser.street_geometry), cut between two map clicks (parser.cut_between).
The section then goes to POST /api/closures as a drawn closure.
"""

from __future__ import annotations

import json
from functools import lru_cache

from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, nearest_points

from app.common import provenance as prov
from app.common.errors import invalid, not_found
from app.common.geo import length_m, to_geojson, to_metric
from app.config import get_settings
from app.m1_disruption import parser
from app.models.base import LineGeometry, Model, Provenance

LIMIT = 20
MAX_SNAP_M = 80.0       # a click farther than this from the street is not on it (= parser.cut_between gap)
REGISTER_SOURCE = "Primăria Timișoara, nomenclatorul stradal / street register"
REGISTER_URL = "https://servicii.primariatm.ro/api/nomenclator/strazi"


class StreetHit(Model):
    streetId: str               # the register's record id: the key for /api/streets/{streetId}/section
    name: str                   # official full name, e.g. "Strada Ardealului"
    codGis: str | None          # the City Hall's GIS code; null for the 20 streets with a provisional name
    type: str                   # "Strada", "Bulevardul", …
    neighbourhood: str | None   # the register's „cartier”
    formerName: str | None      # set when the query matched the former name, not the current one
    hasGeometry: bool           # our OSM extract has ways with this name (the section can be cut)


class StreetSearch(Model):
    query: str
    streets: list[StreetHit]
    provenance: list[Provenance]


class StreetSection(Model):
    streetId: str
    name: str
    codGis: str | None
    geometry: LineGeometry      # WGS84; LineString runs from `from` to `to` when it is one piece
    lengthMeters: int
    whole: bool                 # true: no from/to given, the whole street
    fromPoint: list[float] | None   # [lon, lat] on the street nearest the first click
    toPoint: list[float] | None
    provenance: list[Provenance]


@lru_cache(maxsize=1)
def _records() -> tuple[list[dict], dict[str, dict]]:
    path = get_settings().city_dir / parser.REGISTER_FILE
    raw = json.loads(path.read_text(encoding="utf-8"))["strazi"]
    rows = [r for r in raw if r.get("stare") == "Existenta"]
    return rows, {str(r["id"]): r for r in rows}


def _street_of(rec: dict) -> parser.Street | None:
    """The parser's register entry (the one street_geometry reads) for a raw record."""
    streets, _cur, _old = parser.register()
    cod = str(rec.get("codGis") or "") or None
    return next((s for s in streets if s.name == rec["denumireCompleta"] and s.cod_gis == cod), None)


def _words(rec: dict, key: str) -> list[str]:
    return parser.norm(rec.get(key) or "").split()


def _score(words: list[str], name: list[str]) -> int | None:
    """0 same name, 1 starts with the query's words, 2 starts with the query, 3 every query word starts
    a word, 4 inside; None = no match."""
    if not words or not name:
        return None
    q, n = " ".join(words), " ".join(name)
    if q == n:
        return 0
    if n.startswith(q + " "):
        return 1
    if n.startswith(q):
        return 2
    if all(any(nw.startswith(w) for nw in name) for w in words):
        return 3
    if q in n:
        return 4
    return None


def _has_geometry(rec: dict) -> bool:
    st = _street_of(rec)
    try:
        return bool(st and parser.osm_edges_for(st))
    except FileNotFoundError:
        return False


def _provenance(with_osm: bool) -> list[Provenance]:
    out = [prov.for_file(REGISTER_SOURCE, get_settings().city_dir / parser.REGISTER_FILE, REGISTER_URL)]
    if with_osm:
        p = prov.from_sources("osm")
        out.append(p or prov.for_file("OpenStreetMap (ODbL)", parser._pbf_path(), "https://www.openstreetmap.org"))
    return out


def search(q: str, limit: int = LIMIT) -> StreetSearch:
    """Streets by name, ignoring case, diacritics and the type word („str.”, „bd.”); former names too."""
    toks = parser.norm(q).split()
    typ = toks[0] if toks and toks[0] in parser.STREET_TYPES else None
    words = toks[1:] if typ else toks
    if not words or len(" ".join(words)) < 2:
        raise invalid("Scrieți cel puțin 2 litere din numele străzii / type at least 2 letters of the street name.")
    rows, _by_id = _records()
    ranked = []
    for r in rows:
        cur = _words(r, "numeActual") or [w for w in _words(r, "denumireCompleta") if w not in parser.STREET_TYPES]
        sc, former = _score(words, cur), None
        if sc is None:
            old = _words(r, "numeAnterior")
            if old and old != cur:
                sc = _score(words, old)
                if sc is not None:
                    sc, former = sc + 5, r.get("numeAnterior")
        if sc is None:
            continue
        if typ and parser.norm(r.get("tipArtera") or "") != typ:
            sc += 10  # „bd. Eroilor”: the boulevard first, a street of the same name after
        ranked.append((sc, len(r["denumireCompleta"]), r["denumireCompleta"], r, former))
    ranked.sort(key=lambda h: h[:3])
    hits = [StreetHit(streetId=str(r["id"]), name=r["denumireCompleta"], codGis=str(r.get("codGis") or "") or None,
                      type=r.get("tipArtera") or "", neighbourhood=r.get("cartier") or None, formerName=former,
                      hasGeometry=_has_geometry(r))
            for _s, _l, _n, r, former in ranked[:limit]]
    return StreetSearch(query=q, streets=hits, provenance=_provenance(with_osm=bool(hits)))


def parse_point(raw: str | None, label: str) -> tuple[float, float] | None:
    if raw is None or raw == "":
        return None
    try:
        lon, lat = (float(x) for x in raw.split(","))
    except ValueError:
        raise invalid(f"`{label}` is „lon,lat” in WGS84, e.g. 21.2087,45.7489.") from None
    if not (20.0 < lon < 22.5 and 45.0 < lat < 46.5):
        raise invalid(f"`{label}` ({lon}, {lat}) is not near Timișoara: give „lon,lat”.")
    return lon, lat


def _lines(g) -> LineString | MultiLineString | None:
    parts = [p for p in getattr(g, "geoms", [g]) if p.geom_type == "LineString" and not p.is_empty]
    if not parts:
        return None
    merged = linemerge(parts) if len(parts) > 1 else parts[0]
    return merged if merged.geom_type in ("LineString", "MultiLineString") else None


def section(street_id: str, a: tuple[float, float] | None, b: tuple[float, float] | None) -> StreetSection:
    """The street between the two clicks (both given), or the whole street (neither given)."""
    _rows, by_id = _records()
    rec = by_id.get(str(street_id))
    if rec is None:
        raise not_found(f"No street {street_id} in the register (use GET /api/streets?q=).", "NO_SUCH_STREET")
    if (a is None) != (b is None):
        raise invalid("Give both `from` and `to` (two clicks on the street), or neither for the whole street.")
    st = _street_of(rec)
    try:
        geom = parser.street_geometry(st) if st else None
    except FileNotFoundError:
        geom = None
    if geom is None or geom.is_empty:
        raise invalid(f"„{rec['denumireCompleta']}” has no way with this name in our OpenStreetMap extract: "
                      "draw the section on the map instead.", "NO_STREET_GEOMETRY")
    snapped: list[list[float] | None] = [None, None]
    if a is not None and b is not None:
        gm = to_metric(geom)
        for i, (pt, label) in enumerate(((a, "from"), (b, "to"))):
            d = gm.distance(to_metric(Point(pt)))
            if d > MAX_SNAP_M:
                raise invalid(f"`{label}` is {round(d)} m from {rec['denumireCompleta']}: click on the street "
                              f"(at most {int(MAX_SNAP_M)} m away).", "NOT_ON_STREET")
            near = nearest_points(geom, Point(pt))[0]
            snapped[i] = [round(near.x, 7), round(near.y, 7)]
        cut = parser.cut_between(geom, Point(a), Point(b))
        out = _lines(cut) if cut is not None else None
        if out is None:
            raise invalid("The two clicks are the same place on the street: click the start and the end.",
                          "EMPTY_SECTION")
        if out.geom_type == "LineString" and Point(out.coords[0]).distance(Point(a)) > Point(out.coords[-1]).distance(Point(a)):
            out = LineString(list(out.coords)[::-1])   # from the first click to the second
    else:
        out = _lines(geom)
        if out is None:
            raise invalid(f"„{rec['denumireCompleta']}” has no line geometry in our extract.", "NO_STREET_GEOMETRY")
    return StreetSection(streetId=str(rec["id"]), name=rec["denumireCompleta"],
                         codGis=str(rec.get("codGis") or "") or None, geometry=to_geojson(out),
                         lengthMeters=int(round(length_m(out))), whole=a is None, fromPoint=snapped[0],
                         toPoint=snapped[1], provenance=_provenance(with_osm=True))
