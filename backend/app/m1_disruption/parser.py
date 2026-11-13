"""Deterministic STPT notice parser (SPEC §6.1 item 3). No LLM.

`parse_notice(text)` turns a pasted notice into a draft Closure:
  - window: "8 noiembrie 2026 ... 10:00 – 18:00", "în perioada 07 noiembrie 2026, ora 04:00 –
    12 noiembrie 2026, ora 24:00", "începând de luni, 2 noiembrie 2026" (open end), "de mâine";
  - lines: "linia 4", "liniile M32, M36", "Linia Expres 3" (= E3) -> city route ids;
  - actions -> routeActions: "va fi suspendată" (suspended), "va circula ... pe traseul A – B"
    (shortened, kept stops), "Se suspendă temporar următoarele stații: …" (rerouted, suspended
    stops), "Stațiile deservite: …" (rerouted: stops of the normal pattern between the first and
    last served stop that are not on the list are suspended);
  - "introduce temporar linia … 4b" -> temporaryRoutes, its streets chained on the OSM graph;
  - streets through the city street register (normalised), then OSM ways by the same name;
    "pe tronsonul cuprins între X și Y" cuts the street between X and Y;
  - stop names against the GTFS names on the line's own stop pattern.
Every sentence that yields nothing goes to `unread`; the review screen lists them.

The Closure keeps the notice text in `sourceText`. Nothing here invents a value: what the
text does not say stays null.
"""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import numpy as np
from shapely.geometry import LineString, MultiLineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, nearest_points, substring

from app.common import gtfs
from app.common.city import load_network, route_mode
from app.common.geo import to_geojson, to_metric, to_wgs84
from app.common.timeutil import iso, local_midnight
from app.config import TZ, get_settings, now
from app.models.base import I18n
from app.models.v1 import Closure, ParseResult, RouteAction, TemporaryRoute

log = logging.getLogger(__name__)

OSM_CACHE_VERSION = 1

# ---------------------------------------------------------------------------
# text normalisation
# ---------------------------------------------------------------------------

_ABBREV = {
    "str": "strada", "strazii": "strada", "strazile": "strada",
    "bd": "bulevardul", "bdul": "bulevardul", "b-dul": "bulevardul", "bld": "bulevardul",
    "bul": "bulevardul", "blvd": "bulevardul", "bulevardului": "bulevardul",
    "cal": "calea", "caii": "calea",
    "p-ta": "piata", "pta": "piata", "pietei": "piata", "p-tei": "piata",
    "al": "aleea", "aleii": "aleea",
    "int": "intrarea", "intr": "intrarea",
    "spl": "splaiul", "splaiului": "splaiul",
    "dr": "doctor",
}
STREET_TYPES = ("strada", "bulevardul", "calea", "piata", "aleea", "intrarea", "splaiul", "scuarul")


def fold(s: str) -> str:
    """Lowercase, no diacritics (ă->a, ș/ş->s, ț/ţ->t)."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def norm(s: str) -> str:
    """Folded, dots removed („C.F.R.” = „CFR”), punctuation to spaces, abbreviations expanded."""
    s = fold(s)
    s = s.replace("b-dul", "bdul").replace("p-ta", "pta").replace("p-tei", "ptei")
    s = s.replace(".", " ").replace("’", "").replace("'", "")
    s = re.sub(r"(?<=\b[a-z]) (?=[a-z]\b)", "", s)          # "c f r" -> "cfr" (after dots went)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return " ".join(_ABBREV.get(t, t) for t in s.split())


def _tokens(s: str) -> list[str]:
    return norm(s).split()


# ---------------------------------------------------------------------------
# sentences
# ---------------------------------------------------------------------------

_SHORT_ABBR = {"str", "bd", "bdul", "dr", "nr", "cal", "al", "pta", "spl", "int", "ing", "prof", "sf", "gen"}


def split_sentences(text: str) -> list[str]:
    """Lines first, then '. ' + capital, except after an abbreviation or an initial („C. Brâncoveanu”)."""
    out: list[str] = []
    for line in text.replace("\r", "\n").split("\n"):
        line = line.strip()
        if not line:
            continue
        start = 0
        for m in re.finditer(r"[.!?](?=\s+[A-ZĂÂÎȘŞȚŢ⚠📅])", line):
            word = re.search(r"([\w\-]+)$", line[start:m.start()])
            w = word.group(1) if word else ""
            if len(w) <= 2 or fold(w) in _SHORT_ABBR:
                continue
            out.append(line[start:m.end()].strip())
            start = m.end()
        rest = line[start:].strip()
        if rest:
            out.append(rest)
    return [s for s in out if re.search(r"\w", s)]


# ---------------------------------------------------------------------------
# dates and the window
# ---------------------------------------------------------------------------

MONTHS = {
    "ianuarie": 1, "ian": 1, "februarie": 2, "feb": 2, "martie": 3, "mar": 3, "aprilie": 4, "apr": 4,
    "mai": 5, "iunie": 6, "iun": 6, "iulie": 7, "iul": 7, "august": 8, "aug": 8, "septembrie": 9,
    "sept": 9, "sep": 9, "octombrie": 10, "oct": 10, "noiembrie": 11, "nov": 11, "decembrie": 12, "dec": 12,
}
_DATE_RE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b\.?(?:\s+(\d{4}))?")
_DATE_NUM_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
_TIME_RE = re.compile(r"\b([01]?\d|2[0-4])\s?[:.]\s?([0-5]\d)\b")
_TIME_SPACED_RE = re.compile(r"\b(?:ora|orele|intre|între)?\s*\b([01]?\d|2[0-4]) ([0-5]\d)\b")


@dataclass
class _Stamp:
    pos: int
    day: date
    time: tuple[int, int] | None = None


def _dates_in(sentence: str, ref: datetime) -> list[_Stamp]:
    f = fold(sentence)
    out = []
    for m in _DATE_RE.finditer(f):
        year = int(m.group(3)) if m.group(3) else ref.year
        if year < 2000 or re.search(r"\b(strada|str|bulevardul|bd|b-dul|bdul|calea|piata|aleea)\s*\.?\s*$", f[:m.start()]):
            continue   # a street name („Bd. 16 Decembrie 1989”), not a date
        try:
            out.append(_Stamp(m.start(), date(year, MONTHS[m.group(2)], int(m.group(1)))))
        except ValueError:
            continue
    for m in _DATE_NUM_RE.finditer(f):
        try:
            out.append(_Stamp(m.start(), date(int(m.group(3)), int(m.group(2)), int(m.group(1)))))
        except ValueError:
            continue
    if re.search(r"\b(de )?maine\b", f):
        out.append(_Stamp(f.index("maine"), (ref + timedelta(days=1)).date()))
    elif re.search(r"\b(de )?(astazi|azi)\b", f):
        out.append(_Stamp(0, ref.date()))
    return sorted(out, key=lambda s: s.pos)


def _times_in(sentence: str) -> list[tuple[int, tuple[int, int]]]:
    f = fold(sentence)
    found = [(m.start(), (int(m.group(1)), int(m.group(2)))) for m in _TIME_RE.finditer(f)
             if not re.match(r"\d{4}", f[m.start():])]
    if not found:  # STPT text with the colon stripped: "10 00 – 18 00"
        for m in _TIME_SPACED_RE.finditer(f):
            tail = f[m.end():m.end() + 12]
            if re.match(r"\s*(" + "|".join(MONTHS) + r")\b", tail):
                continue
            found.append((m.start(1), (int(m.group(1)), int(m.group(2)))))
    return found


def _at(day: date, hm: tuple[int, int] | None, default_end: bool = False) -> datetime:
    if hm is None:
        return local_midnight(day + timedelta(days=1)) if default_end else local_midnight(day)
    h, m = hm
    if h == 24:
        return local_midnight(day + timedelta(days=1)) + timedelta(minutes=m)
    return local_midnight(day).replace(hour=h, minute=m)


def open_end_default() -> datetime:
    """End of an open-ended notice („până la finalizarea lucrărilor”): the last day of the GTFS feed."""
    try:
        _first, last = gtfs.coverage()
        return local_midnight(last) + timedelta(hours=23, minutes=59, seconds=59)
    except Exception:  # no feed: one year after today is still a guess, so keep it short and visible
        return local_midnight(now().date() + timedelta(days=30))


@dataclass
class WindowFound:
    start: datetime
    end: datetime
    open_end: bool


def window_from(sentence: str, ref: datetime) -> WindowFound | None:
    dates = _dates_in(sentence, ref)
    if not dates:
        return None
    times = _times_in(sentence)
    for i, d in enumerate(dates):
        nxt = dates[i + 1].pos if i + 1 < len(dates) else 10**9
        own = [t for p, t in times if d.pos < p < nxt]
        if own:
            d.time = own[0]
    f = fold(sentence)
    if len(dates) >= 2:
        a, b = dates[0], dates[1]
        return WindowFound(_at(a.day, a.time), _at(b.day, b.time, default_end=True), False)
    d = dates[0]
    if len(times) >= 2:
        t1, t2 = times[0][1], times[1][1]
        return WindowFound(_at(d.day, t1), _at(d.day, t2, default_end=True), False)
    if re.search(r"\b(incepand|incepind|de la data|din data)\b", f):
        return WindowFound(_at(d.day, d.time), open_end_default(), True)
    return WindowFound(_at(d.day, d.time), _at(d.day, None, default_end=True), False)


# ---------------------------------------------------------------------------
# GTFS lines, directions and stop names
# ---------------------------------------------------------------------------

_LINE_KW = r"(?:linia|liniile|liniei|liniilor|linii|linie|autobuzul|tramvaiul|troleibuzul)"
_LINE_QUAL = r"(?:\s+(?:de\s+)?(?:autobuz|tramvai|troleibuz|metropolitane|metropolitana|scolar|scolara|scolare))*"
_LINE_TOK = r"(?:expres\s*\d{1,2}[a-z]?|[a-z]{0,2}\s?\d{1,3}[a-z]?)"
_LINE_RE = re.compile(r"\b" + _LINE_KW + _LINE_QUAL + r"\s+(" + _LINE_TOK + r"(?:(?:\s*,\s*|\s+si\s+|\s+)" + _LINE_TOK + r")*)\b")
_LINE_TOK_RE = re.compile(_LINE_TOK)


@lru_cache(maxsize=1)
def _routes_by_short() -> dict[str, str]:
    return {r["shortName"].lower(): r["id"] for r in load_network().routes}


def line_tokens(sentence: str) -> list[str]:
    """Short names the sentence names after a „linia …” keyword, normalised („Expres 3” -> „e3”)."""
    f = fold(sentence)
    out: list[str] = []
    for m in _LINE_RE.finditer(f):
        for t in _LINE_TOK_RE.findall(m.group(1)):
            t = t.strip()
            t = re.sub(r"^expres\s*", "e", t).replace(" ", "")
            if re.fullmatch(r"(19|20)\d\d", t):
                continue
            if t not in out:
                out.append(t)
    return out


def _route_for(token: str) -> str | None:
    return _routes_by_short().get(token.lower())


def _patterns_of(route_id: str) -> dict[int, gtfs.Pattern]:
    pats = gtfs.stop_patterns()
    return {d: pats[(route_id, d)] for d in (0, 1) if (route_id, d) in pats}


@lru_cache(maxsize=1)
def _stop_names() -> dict[str, str]:
    return {s["id"]: s["name"] for s in load_network().stops}


_DESCRIPTOR = {"depou", "depoul", "capat", "capatul", "statia", "statie", "bucla"}


def _split_name(name: str) -> tuple[list[str], list[str]]:
    """'Opre Gogu (Ardealului)' -> (['opre','gogu'], ['ardealului']). Parenthesis = street or landmark.

    A leading descriptor („Depou Dâmbovița”, „Capăt …”) is dropped from the base."""
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", name.strip())
    base, par = (m.group(1), m.group(2)) if m else (name, "")
    par = re.sub(r"^(pe|din|la)\s+", "", fold(par))
    toks = _tokens(base)
    while len(toks) > 1 and toks[0] in _DESCRIPTOR:
        toks = toks[1:]
    return toks, _tokens(par)


def _tok_in(t: str, pool: list[str]) -> bool:
    """A token is in the pool; one letter matches a word with that initial („C.” = „Constantin”)."""
    for p in pool:
        if t == p or (len(t) == 1 and p.startswith(t)) or (len(p) == 1 and t.startswith(p)):
            return True
    return False


def _name_score(notice: str, gtfs_name: str) -> int:
    """3 exact, 2 same base and paren agrees, 1 notice words all inside the GTFS name, 0 no match."""
    if norm(notice) == norm(gtfs_name):
        return 3
    nb, npar = _split_name(notice)
    gb, gpar = _split_name(gtfs_name)
    if not nb:
        return 0
    if nb == gb and (not npar or not gpar or all(_tok_in(t, gpar + gb) for t in npar)
                     or all(_tok_in(t, npar) for t in gpar)):
        return 2
    pool = gb + gpar
    if all(_tok_in(t, pool) for t in nb) and (not npar or any(_tok_in(t, pool) for t in npar)):
        if len(nb) == 1 and len(nb[0]) <= 2:
            return 0
        return 1
    return 0


def match_stop(name: str, stop_ids: Iterable[str]) -> list[str]:
    """GTFS stop ids on a pattern whose name matches a notice name (best level only)."""
    names = _stop_names()
    best, hits = 0, []
    for sid in dict.fromkeys(stop_ids):
        sc = _name_score(name, names.get(sid, ""))
        if sc > best:
            best, hits = sc, [sid]
        elif sc and sc == best:
            hits.append(sid)
    return hits


def _headsign_dir(route_id: str, phrase: str) -> int | None:
    """Direction id whose headsign or last stop matches the place after „către”."""
    pats = _patterns_of(route_id)
    target = _split_name(phrase)[0]
    if not target:
        return None
    names = _stop_names()
    scored = []
    for d, p in pats.items():
        hs = _tokens(p.headsign) + _tokens(names.get(p.stop_ids[-1], ""))
        hit = sum(1 for t in target if _tok_in(t, hs))
        scored.append((hit, d))
    scored.sort(reverse=True)
    if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    return None


def _city_dir(route_id: str, inbound: bool) -> int | None:
    """„intrare în oraș” = the direction whose headsign says Timișoara; „ieșire” = the other."""
    pats = _patterns_of(route_id)
    tim = [d for d, p in pats.items() if "timisoara" in fold(p.headsign)]
    if len(tim) != 1:
        return None
    return tim[0] if inbound else 1 - tim[0]


def _best_dir_by_names(route_id: str, names: list[str]) -> int | None:
    scores = []
    for d, p in _patterns_of(route_id).items():
        hits = [match_stop(n, p.stop_ids) for n in names]
        idx = [min(p.stop_ids.index(h) for h in hs) for hs in hits if hs]
        ordered = sum(1 for a, b in zip(idx, idx[1:]) if b > a)
        scores.append((len(idx), ordered, d))
    scores.sort(reverse=True)
    if scores and scores[0][0] and (len(scores) == 1 or scores[0][:2] != scores[1][:2]):
        return scores[0][2]
    return None


# ---------------------------------------------------------------------------
# street register (gazetteer)
# ---------------------------------------------------------------------------

REGISTER_FILE = "nomenclator-strazi.json"


@dataclass(frozen=True)
class Street:
    name: str              # official full name, e.g. "Strada Martir Gogu Opre"
    cod_gis: str | None
    type: str              # folded type word, e.g. "strada"
    keys: tuple[str, ...]  # normalised names that point to it (current first, old last)


@lru_cache(maxsize=1)
def register() -> tuple[list[Street], dict[str, Street], dict[str, Street]]:
    """Streets, current-name index and old-name index (old names are a fallback only)."""
    path = get_settings().city_dir / REGISTER_FILE
    raw = json.loads(path.read_text(encoding="utf-8"))["strazi"]
    streets, cur, old = [], {}, {}
    for r in sorted(raw, key=lambda r: r.get("stare") != "Existenta"):
        typ = norm(r.get("tipArtera") or "")
        full = norm(r["denumireCompleta"])
        actual = norm(r.get("numeActual") or "")
        keys = [full]
        if typ and actual:
            keys.append(f"{typ} {actual}")
        if " doctor " in f" {full} ":
            keys.append(full.replace("doctor ", ""))
        olds = []
        prev = norm(r.get("numeAnterior") or "")
        if typ and prev and len(prev.split()) <= 4 and prev != actual:
            olds.append(f"{typ} {prev}")
        st = Street(r["denumireCompleta"], str(r.get("codGis") or "") or None, typ, tuple(keys + olds))
        streets.append(st)
        for k in keys:
            cur.setdefault(k, st)
        for k in olds:
            old.setdefault(k, st)
    return streets, cur, old


def resolve_street(text: str) -> Street | None:
    """One street name as written in a notice -> the register entry, or None."""
    _s, cur, old = register()
    toks = norm(text).split()
    if toks and toks[0] not in STREET_TYPES and len(toks) <= 5:
        # a bare name („Ardealului”): try every type, accept only a single hit
        hits = {cur[f"{t} {' '.join(toks)}"].name: cur[f"{t} {' '.join(toks)}"]
                for t in STREET_TYPES if f"{t} {' '.join(toks)}" in cur}
        return next(iter(hits.values())) if len(hits) == 1 else None
    for n in range(min(len(toks), 7), 1, -1):
        k = " ".join(toks[:n])
        if k in cur:
            return cur[k]
    for n in range(min(len(toks), 7), 1, -1):
        k = " ".join(toks[:n])
        if k in old:
            return old[k]
    return None


def streets_in(sentence: str) -> list[tuple[int, Street]]:
    """Streets named in a sentence, by position (token index): longest register key at each type word."""
    _s, cur, old = register()
    toks = norm(sentence).split()
    out, i = [], 0
    while i < len(toks):
        if toks[i] in STREET_TYPES:
            hit = None
            for n in range(min(7, len(toks) - i), 1, -1):
                k = " ".join(toks[i:i + n])
                if k in cur:
                    hit = (n, cur[k])
                    break
            if hit is None:
                for n in range(min(7, len(toks) - i), 1, -1):
                    k = " ".join(toks[i:i + n])
                    if k in old:
                        hit = (n, old[k])
                        break
            if hit:
                out.append((i, hit[1]))
                i += hit[0]
                continue
        i += 1
    return out


# ---------------------------------------------------------------------------
# OSM streets and tram tracks ($DATA_DIR/osm/timisoara.osm.pbf, read with pyrosm, cached)
# ---------------------------------------------------------------------------


@dataclass
class OsmStreets:
    names: list[str]                 # normalised name per edge
    u: np.ndarray
    v: np.ndarray
    length: np.ndarray
    coords: list[np.ndarray]         # WGS84 [lon, lat] per edge
    node_xy: dict[int, tuple[float, float]]
    by_name: dict[str, list[int]]
    tram: list[np.ndarray]           # railway=tram ways, in their drawn order (oneway)
    source: str                      # provenance text: file + date


def _pbf_path() -> Path:
    return get_settings().data_dir / "osm" / "timisoara.osm.pbf"


def _build_osm(pbf: Path) -> OsmStreets:
    import pyrosm  # slow import, only when building

    osm = pyrosm.OSM(str(pbf))
    nodes, edges = osm.get_network(network_type="driving+service", nodes=True)
    names = [norm(n) if isinstance(n, str) else "" for n in edges["name"]]
    coords = [np.asarray(g.coords, dtype=float) for g in edges.geometry]
    by_name: dict[str, list[int]] = {}
    for i, n in enumerate(names):
        if n:
            by_name.setdefault(n, []).append(i)
    node_xy = {int(i): (float(x), float(y)) for i, x, y in zip(nodes["id"], nodes["lon"], nodes["lat"])}
    rails = osm.get_data_by_custom_criteria(custom_filter={"railway": ["tram"]}, filter_type="keep",
                                            keep_nodes=False, keep_relations=False)
    tram = []
    if rails is not None:
        for g in rails.geometry:
            for part in getattr(g, "geoms", [g]):
                if part.geom_type == "LineString":
                    tram.append(np.asarray(part.coords, dtype=float))
    return OsmStreets(names=names, u=edges["u"].to_numpy(dtype=np.int64), v=edges["v"].to_numpy(dtype=np.int64),
                      length=edges["length"].to_numpy(dtype=float), coords=coords, node_xy=node_xy,
                      by_name=by_name, tram=tram, source="")


@lru_cache(maxsize=1)
def osm_streets() -> OsmStreets:
    pbf = _pbf_path()
    if not pbf.is_file():
        raise FileNotFoundError(f"OSM extract missing: {pbf} (run `make data`)")
    st = pbf.stat()
    key = hashlib.sha1(f"{OSM_CACHE_VERSION}:{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()[:12]
    cache = get_settings().cache_dir / f"osm_streets_v{OSM_CACHE_VERSION}_{key}.pkl"
    data = None
    if cache.is_file():
        try:
            data = pickle.loads(cache.read_bytes())
        except Exception:
            data = None
    if data is None:
        data = _build_osm(pbf)
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_bytes(pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL))
        tmp.replace(cache)
    data.source = f"OpenStreetMap (ODbL), {pbf.name}"
    return data


def osm_edges_for(street: Street) -> list[int]:
    """OSM edge indices whose name is the street (same normalised name, or same type + all its words)."""
    o = osm_streets()
    for k in street.keys:
        if k in o.by_name:
            return list(o.by_name[k])
    words = [w for w in norm(street.name).split() if w not in STREET_TYPES]
    for n, idx in o.by_name.items():
        parts = n.split()
        if parts and parts[0] == street.type and all(w in parts for w in words):
            return list(idx)
    return []


def street_geometry(street: Street) -> BaseGeometry | None:
    """WGS84 (Multi)LineString of the street's OSM ways, merged."""
    o = osm_streets()
    idx = osm_edges_for(street)
    if not idx:
        return None
    return linemerge([LineString(o.coords[i]) for i in idx])


def _parts(g: BaseGeometry) -> list[LineString]:
    return [p for p in getattr(g, "geoms", [g]) if p.geom_type == "LineString" and not p.is_empty]


def cut_between(geom: BaseGeometry, a: BaseGeometry, b: BaseGeometry, max_gap_m: float = 80.0) -> BaseGeometry | None:
    """The part of a (Multi)LineString between the points closest to `a` and `b` (WGS84 in and out)."""
    gm, am, bm = to_metric(geom), to_metric(a), to_metric(b)
    pieces = []
    for part in _parts(gm):
        if part.distance(am) > max_gap_m or part.distance(bm) > max_gap_m:
            continue
        pa = part.project(nearest_points(part, am)[0])
        pb = part.project(nearest_points(part, bm)[0])
        if abs(pb - pa) < 1.0:
            continue
        pieces.append(substring(part, min(pa, pb), max(pa, pb)))
    if not pieces:
        # the street is several ways (dual carriageway, splits at squares): keep what lies in the
        # corridor between the two points instead (flat-capped band along a-b, 60 m each side)
        ap, bp = nearest_points(gm, am)[0], nearest_points(gm, bm)[0]
        if ap.distance(bp) < 1.0:
            return None
        band = LineString([ap, bp]).buffer(60.0, cap_style="flat")
        clipped = gm.intersection(band)
        pieces = [p for p in _parts(clipped) if p.length >= 5.0]
        if not pieces:
            return None
        merged = linemerge(pieces)
        return to_wgs84(merged)
    out = to_wgs84(pieces[0] if len(pieces) == 1 else MultiLineString(pieces))
    return out


def tram_along(geom: BaseGeometry, max_dist_m: float = 30.0, min_share: float = 0.5) -> list[LineString]:
    """Tram ways (railway=tram, in their drawn order) that run along a street geometry."""
    o = osm_streets()
    gm = to_metric(geom)
    buf = gm.buffer(max_dist_m)
    minx, miny, maxx, maxy = geom.bounds
    pad = 0.002
    out = []
    for c in o.tram:
        if c[:, 0].max() < minx - pad or c[:, 0].min() > maxx + pad or c[:, 1].max() < miny - pad or c[:, 1].min() > maxy + pad:
            continue
        line = LineString(c)
        lm = to_metric(line)
        if lm.length <= 0 or not lm.intersects(buf):
            continue
        inside = lm.intersection(buf).length
        if inside / lm.length >= min_share or inside >= 150:
            out.append(LineString(c))
    return out


def _graph():
    return _graph_cached(id(osm_streets()))


@lru_cache(maxsize=1)
def _graph_cached(_key: int):
    import networkx as nx

    o = osm_streets()
    g = nx.Graph()
    for i in range(len(o.names)):
        u, v, ln = int(o.u[i]), int(o.v[i]), float(o.length[i])
        old = g.get_edge_data(u, v)
        if old is None or old["length"] > ln:
            g.add_edge(u, v, length=ln, idx=i)
    return g


def _street_nodes(edge_idx: list[int]) -> set[int]:
    o = osm_streets()
    return {int(o.u[i]) for i in edge_idx} | {int(o.v[i]) for i in edge_idx}


def _nearest_node(nodes: Iterable[int], lon: float, lat: float) -> int | None:
    o = osm_streets()
    best, bd = None, float("inf")
    k = np.cos(np.radians(lat))
    for n in nodes:
        x, y = o.node_xy.get(n, (None, None))
        if x is None:
            continue
        d = ((x - lon) * k) ** 2 + (y - lat) ** 2
        if d < bd:
            best, bd = n, d
    return best


def _junction(a_nodes: set[int], b_nodes: set[int], prev: tuple[float, float] | None) -> int | None:
    """A node shared by two streets (nearest to the previous point), else the B node nearest to A."""
    o = osm_streets()
    shared = a_nodes & b_nodes
    if shared:
        if prev is None:
            return min(shared)
        return _nearest_node(shared, *prev)
    best, bd = None, float("inf")
    a_xy = np.array([o.node_xy[n] for n in a_nodes if n in o.node_xy])
    if a_xy.size == 0:
        return None
    k = np.cos(np.radians(a_xy[0, 1]))
    for n in b_nodes:
        if n not in o.node_xy:
            continue
        x, y = o.node_xy[n]
        d = float((((a_xy[:, 0] - x) * k) ** 2 + (a_xy[:, 1] - y) ** 2).min())
        if d < bd:
            best, bd = n, d
    return best


def chain_streets(streets: list[Street], end_hint: tuple[float, float] | None = None) -> LineString | None:
    """A path that follows the named streets in order, on the OSM street graph.

    Each leg runs from the junction with the previous street to the junction with the next one,
    preferring edges of the street being followed (others cost 8x, so short connectors still work).
    The last street ends at `end_hint` (e.g. the terminus stop it replaces), else at its far end.
    """
    import networkx as nx

    o = osm_streets()
    g = _graph()
    edge_sets = [set(osm_edges_for(s)) for s in streets]
    if len([e for e in edge_sets if e]) < 2:
        return None
    named = [(s, e) for s, e in zip(streets, edge_sets) if e]
    nodes = [_street_nodes(list(e)) for _s, e in named]
    waypoints: list[int] = []
    prev_xy = None
    for i in range(len(named) - 1):
        j = _junction(nodes[i], nodes[i + 1], prev_xy)
        if j is None:
            continue
        waypoints.append(j)
        prev_xy = o.node_xy.get(j)
    if not waypoints:
        return None
    last_nodes = nodes[-1]
    if end_hint is not None:
        end = _nearest_node(last_nodes, *end_hint)
    else:
        sx, sy = o.node_xy[waypoints[-1]]
        k = np.cos(np.radians(sy))
        end = max(last_nodes, key=lambda n: ((o.node_xy[n][0] - sx) * k) ** 2 + (o.node_xy[n][1] - sy) ** 2)
    waypoints.append(end)
    coords: list[tuple[float, float]] = []
    for leg in range(len(waypoints) - 1):
        a, b = waypoints[leg], waypoints[leg + 1]
        if a == b:
            continue
        prefer = named[min(leg + 1, len(named) - 1)][1]

        def w(u, v, d, prefer=prefer):
            return d["length"] * (1.0 if d["idx"] in prefer else 8.0)

        try:
            path = nx.shortest_path(g, a, b, weight=w)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        for u, v in zip(path, path[1:]):
            idx = g[u][v]["idx"]
            c = o.coords[idx]
            seg = c if int(o.u[idx]) == u else c[::-1]
            pts = [tuple(p) for p in seg]
            if coords and coords[-1] == pts[0]:
                pts = pts[1:]
            coords.extend(pts)
    if len(coords) < 2:
        return None
    return LineString(coords)


# ---------------------------------------------------------------------------
# cause (GTFS-RT enum), for the outputs of a pasted notice
# ---------------------------------------------------------------------------


def infer_cause(text: str) -> str:
    """MAINTENANCE for track and equipment works, CONSTRUCTION for roadworks, else OTHER_CAUSE (SPEC §6.1.11)."""
    f = fold(text)
    if re.search(r"mentenant|infrastructura de tramvai|liniile de tramvai|linia de tramvai", f):
        return "MAINTENANCE"
    if re.search(r"lucrar|reparati|carosabil|santier|inchider|inchis", f):
        return "CONSTRUCTION"
    return "OTHER_CAUSE"


# ---------------------------------------------------------------------------
# the parser
# ---------------------------------------------------------------------------

_COURTESY = re.compile(r"\b(recomanda|rugati|multumes|multumim|va multumim|consulte|consultati|planifica|"
                       r"planifice|inconveniente|disconfortul|intelegere)\b")
_CLOSURE_KW = re.compile(r"\b(lucrar\w*|inchis\w*|inchider\w*|restrictiona\w*|restrictii\w*|mentenanta|reparati\w*|santier\w*)\b")
_SUSPEND_LINE = re.compile(r"\b(va fi suspendat\w*|vor fi suspendat\w*|se suspenda circulatia|nu va circula|nu vor circula)\b")
_SUSPEND_STOPS = re.compile(r"\bse suspenda\w*\b[^:]*\bstati\w*[^:]*:\s*(.+)$")
_SERVED_STOPS = re.compile(r"\bstati\w*\s+(?:deservite|traseu\s+(?:tur|retur))[^:]*:\s*(.+)$")
_ROUTE_LIST = re.compile(r"\bpe traseul\s*:?\s*(?!obisnuit|normal|existent)(.+)$")
_DIRECTION_TO = re.compile(r"\bsens\w*(?: de (?:deplasare|mers|circulatie))?\s+(?:catre|spre)\s+(.+?)(?:\s+[-–]\s+|$)")
_INBOUND = re.compile(r"\bsens\w*\s+de\s+intrare\b")
_OUTBOUND = re.compile(r"\bsens\w*\s+de\s+iesire\b")
_TUR = re.compile(r"\btraseu\w*\s+tur\b|\bstatii traseu tur\b")
_RETUR = re.compile(r"\btraseu\w*\s+retur\b")
_BOTH_DIRS = re.compile(r"\btur\s*[-–]\s*retur\b|\bambele sensuri\b")
_INTRODUCE = re.compile(r"\bintrodu\w*\s+(?:temporar\s+)?(?:o\s+)?(?:noua\s+)?linia\b")
_REROUTE = re.compile(r"\b(vor fi deviat\w*|va fi deviat\w*|modificat\w* temporar|traseu\w* de deviere|"
                      r"nu vor mai fi utilizate|(?:traseul|traseele)\b[^.]*\b(?:vor|va) fi modificat\w*)\b")
_NOT_A_CLOSURE = re.compile(r"\b(prelungit\w*|programul|programele|programe|graficul)\b")
_MODE_WORD = {"autobuz": "bus", "tramvai": "tram", "troleibuz": "trolleybus"}


def _split_list(raw: str) -> list[str]:
    """'A, B (x, y), C și D.' -> ['A', 'B (x, y)', 'C', 'D'] — commas, ' – ' and the last 'și', outside parentheses."""
    raw = raw.strip().rstrip(".;").strip()
    raw = re.sub(r"^[-–]\s*", "", raw)
    items, depth, cur = [], 0, ""
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if depth == 0 and (ch == "," or (ch in "–-" and raw[i - 1:i] == " " and raw[i + 1:i + 2] == " ")):
            items.append(cur)
            cur = ""
            i += 1
            continue
        cur += ch
        i += 1
    items.append(cur)
    out = []
    for it in items:
        it = it.strip()
        if not it:
            continue
        parts = re.split(r"\s+(?:și|si)\s+(?![^(]*\))", it)
        out += [p.strip() for p in parts if p.strip()]
    return out


def _stop_hits(route_ids: list[str], items: list[str]) -> int:
    """How many items match a stop on the stop patterns of these lines."""
    stops = [s for r in route_ids for p in _patterns_of(r).values() for s in p.stop_ids]
    return sum(1 for it in items if match_stop(it, stops))


def _looks_like_streets(items: list[str]) -> bool:
    typed = sum(1 for it in items if norm(it).split()[:1] and norm(it).split()[0] in STREET_TYPES)
    return typed >= max(2, len(items) // 2)


@dataclass
class _Action:
    route_id: str
    direction_id: int | None
    action: str
    names: list[str] | None = None
    served: bool = False        # names are the served stops (11060 style), not the suspended ones
    keep: list[str] | None = None
    suspended: list[str] | None = None


@dataclass
class _State:
    lines: list[str] = field(default_factory=list)            # current route ids
    unknown_lines: list[str] = field(default_factory=list)    # named but not in the GTFS (S8, 4b)
    direction: dict[str, int | None] = field(default_factory=dict)
    dir_phrase: str | None = None
    inbound: bool | None = None


def _expand(a: _Action) -> list[RouteAction]:
    """Resolve the names of one action on the line's stop pattern(s)."""
    pats = _patterns_of(a.route_id)
    dirs = [a.direction_id] if a.direction_id is not None else sorted(pats)
    if a.action == "suspended":
        return [RouteAction(routeId=a.route_id, directionId=a.direction_id, action="suspended",
                            stopNames=a.names)]
    out = []
    for d in dirs:
        p = pats.get(d)
        if p is None:
            continue
        order = list(p.stop_ids)
        hits = [h for n in (a.names or []) for h in match_stop(n, order)]
        if a.action == "shortened":
            if not hits:
                continue
            idx = sorted(order.index(h) for h in hits)
            keep = _trim_span(order, idx[0], idx[-1], a.names or [])
            out.append(RouteAction(routeId=a.route_id, directionId=d, action="shortened",
                                   keepStopIds=keep, stopNames=a.names))
        elif a.served:
            served = set(hits)
            idx = sorted(order.index(h) for h in served)
            susp = [s for s in order[idx[0]:idx[-1] + 1] if s not in served] if len(idx) >= 2 else []
            # the notice lists the stops still served: only the suspended ones go in the action
            # (stopNames on a rerouted action are read as suspended names, so the served list stays out)
            out.append(RouteAction(routeId=a.route_id, directionId=d, action="rerouted",
                                   suspendedStopIds=susp, stopNames=None))
        else:
            susp = [s for s in order if s in set(hits)]
            out.append(RouteAction(routeId=a.route_id, directionId=d, action="rerouted",
                                   suspendedStopIds=susp, stopNames=a.names))
    if not out and a.action == "rerouted" and a.direction_id is not None:
        out.append(RouteAction(routeId=a.route_id, directionId=a.direction_id, action="rerouted",
                               suspendedStopIds=[], stopNames=a.names))
    return out


@lru_cache(maxsize=1)
def _all_stop_ids() -> tuple[str, ...]:
    return tuple(s["id"] for s in load_network().stops)


def _adjacent(first: set[str], then: set[str], gap: int = 4) -> bool:
    """Some GTFS stop pattern visits a stop of `first`, then within `gap` stops one of `then`."""
    for p in gtfs.stop_patterns().values():
        o = p.stop_ids
        for i, sid in enumerate(o):
            if sid in first and any(x in then for x in o[i + 1:i + 1 + gap]):
                return True
    return False


def _trim_span(order: list[str], lo: int, hi: int, names: list[str]) -> list[str]:
    """Kept stops of a shortened line: the pattern between the first and last named stop.

    When the notice's route leaves the pattern at an end of that span („… Piața Maria – Gheorghe
    Doja …”) and no GTFS pattern links that end stop to the next named place, the end stop is a
    platform the new route does not use (Piața Maria has three), so it is not kept.
    """
    keep = order[lo:hi + 1]
    if len(keep) < 3 or not names:
        return keep
    on = [(i, match_stop(n, order)) for i, n in enumerate(names)]
    on = [(i, hs) for i, hs in on if hs]
    forward = min(order.index(h) for h in on[0][1]) <= min(order.index(h) for h in on[-1][1])
    seq = list(range(len(names))) if forward else list(reversed(range(len(names))))
    pos = {i: k for k, i in enumerate(seq)}
    end_name = next(i for i, hs in on if order[hi] in hs)
    start_name = next(i for i, hs in on if order[lo] in hs)
    k_end, k_start = pos[end_name], pos[start_name]
    if k_end + 1 < len(seq):
        nxt = names[seq[k_end + 1]]
        if not match_stop(nxt, order):
            x = set(match_stop(nxt, _all_stop_ids()))
            if x and not _adjacent({order[hi]}, x):
                keep = keep[:-1]
    if k_start - 1 >= 0:
        prv = names[seq[k_start - 1]]
        if not match_stop(prv, order):
            x = set(match_stop(prv, _all_stop_ids()))
            if x and not _adjacent(x, {order[lo]}):
                keep = keep[1:]
    return keep


def _merge_actions(actions: list[_Action]) -> list[_Action]:
    """One action per (route, direction): later, more specific sentences refine earlier ones."""
    merged: dict[tuple[str, int | None], _Action] = {}
    for a in actions:
        key = (a.route_id, a.direction_id)
        old = merged.get(key)
        if old is None or a.names or old.action == "rerouted" and not old.names:
            if old is not None and old.action == "suspended" and a.action != "suspended":
                continue
            merged[key] = a
    # a rerouted action with no direction and no stops is dropped when a per-direction one exists
    for (rid, d), a in list(merged.items()):
        if d is None and a.action == "rerouted" and not a.names and any(
                k[0] == rid and k[1] is not None for k in merged):
            del merged[(rid, d)]
    return list(merged.values())


@dataclass
class ParseDetail:
    """What the parser found, for build.py and tests (not part of the API response)."""
    closure: Closure
    unread: list[str]
    window: WindowFound | None
    closure_streets: list[Street]
    section: tuple[Street, Street] | None
    tram: bool
    lines_unknown: list[str]
    cause: str


def _closure_geometry(sentence: str, streets: list[tuple[int, Street]]) -> tuple[BaseGeometry | None, list[Street], tuple[Street, Street] | None, bool]:
    """Geometry of the closed section named in the closure sentence."""
    f = norm(sentence)
    tram = bool(re.search(r"\btramvai\b", f))
    if not streets:
        return None, [], None, tram
    kw = _CLOSURE_KW.search(f)
    kw_tok = len(f[:kw.start()].split()) if kw else 0
    after_kw = [(i, s) for i, s in streets if i >= kw_tok]
    if after_kw:
        streets = after_kw + [(i, s) for i, s in streets if i < kw_tok]
    main = streets[0][1]
    section = None
    geom = None
    try:
        base = street_geometry(main)
    except FileNotFoundError:
        base = None
    m = re.search(r"\b(?:tronson\w*|portiune\w*|sector\w*)\b.*?\bintre\b", f)
    if m and len(streets) >= 3:
        after = [s for i, s in streets if i > len(f[:m.end()].split()) - 1]
        if len(after) >= 2:
            section = (after[0], after[1])
    elif re.search(r"\bzona\b", f) and len(streets) >= 2 and streets[1][1].type == "piata":
        section = (streets[1][1], streets[1][1])
    if base is not None and section is not None:
        ga, gb = street_geometry(section[0]), street_geometry(section[1])
        if ga is not None and gb is not None:
            if section[0] is section[1]:
                near = to_wgs84(to_metric(ga).buffer(200))
                geom = base.intersection(near)
                geom = linemerge(_parts(geom)) if not geom.is_empty else None
            else:
                pa = nearest_points(base, ga)[0]
                pb = nearest_points(base, gb)[0]
                geom = cut_between(base, pa, pb)
    if geom is None:
        geom = base
    if geom is not None and tram:
        rails = tram_along(geom)
        if rails:
            geom = linemerge(rails)
    return geom, [s for _i, s in streets], section, tram


def parse_detail(text: str, reference: datetime | None = None) -> ParseDetail:
    ref = (reference or now()).astimezone(TZ)
    sentences = split_sentences(text)
    st = _State()
    unread: list[str] = []
    window: WindowFound | None = None
    route_ids: list[str] = []
    actions: list[_Action] = []
    temp: dict[str, TemporaryRoute] = {}
    unknown_lines: list[str] = []
    geom = None
    closure_streets: list[Street] = []
    section = None
    tram = False
    whole = fold(text)

    for sent in sentences:
        f = fold(sent)
        used = False
        n_actions = len(actions)

        # window: the first sentence that has a date
        if window is None:
            w = window_from(sent, ref)
            if w is not None:
                window, used = w, True

        # lines named here; a sentence that names lines sets the current lines
        toks = line_tokens(sent)
        rids = [r for r in (_route_for(t) for t in toks) if r]
        unknown = [t for t in toks if _route_for(t) is None]
        for r in rids:
            if r not in route_ids:
                route_ids.append(r)
        for t in unknown:
            if t not in unknown_lines:
                unknown_lines.append(t)
        if rids or unknown:
            st.lines, st.unknown_lines = rids, unknown
            st.direction = {}
            used = True

        # temporary line: "introduce temporar linia de autobuz 4b"
        if _INTRODUCE.search(f) and unknown:
            mode = next((m for w_, m in _MODE_WORD.items() if re.search(rf"\b{w_}\b", f)), "bus")
            for t in unknown:
                temp.setdefault(t, TemporaryRoute(shortName=t, mode=mode, streets=[], stopIds=None, geometry=None))
            used = True

        # direction context
        dm = _DIRECTION_TO.search(f)
        if dm and st.lines:
            for r in st.lines:
                st.direction[r] = _headsign_dir(r, dm.group(1))
            used = True
        elif _INBOUND.search(f) or _OUTBOUND.search(f):
            for r in st.lines:
                st.direction[r] = _city_dir(r, bool(_INBOUND.search(f)))
            used = True
        elif _TUR.search(f) or _RETUR.search(f):
            for r in st.lines:
                st.direction[r] = None   # resolved from the stop names below
            st.dir_phrase = "retur" if _RETUR.search(f) else "tur"
            used = True

        # suspended whole line(s)
        if _SUSPEND_LINE.search(f) and rids and not _SUSPEND_STOPS.search(f):
            for r in rids:
                actions.append(_Action(r, None, "suspended"))
            used = True

        # list of stops suspended / served
        sm = _SUSPEND_STOPS.search(f)
        vm = _SERVED_STOPS.search(f)
        if (sm or vm) and st.lines:
            # take the list from the original text (keeps diacritics for display)
            raw = sent.split(":", 1)[1] if ":" in sent else sent
            names = _split_list(raw)
            for r in st.lines:
                d = st.direction.get(r)
                if d is None:
                    d = _best_dir_by_names(r, names)
                actions.append(_Action(r, d, "rerouted", names=names, served=bool(vm)))
            used = True

        # "pe traseul A – B – C": kept stops of a shortened line, or the streets of a temporary line
        rm = _ROUTE_LIST.search(f) if not (sm or vm) else None
        if rm:
            raw = sent[rm.start(1):] if len(sent) == len(f) else rm.group(1)
            raw = re.split(r",\s*(?:cu\s+retur|tur\s*[-–]\s*retur|urm[aâ]nd)", raw, maxsplit=1, flags=re.I)[0]
            items = _split_list(raw)
            temp_names = [t for t in st.unknown_lines if t in temp] or [t for t in unknown if t in temp]
            if len(items) >= 2 and temp_names:
                for t in temp_names:
                    temp[t] = temp[t].model_copy(update={"streets": items})
                used = True
            elif len(items) >= 2 and rids and _stop_hits(rids, items) >= 2:
                both = bool(_BOTH_DIRS.search(f))
                for r in rids:
                    d = None if both else st.direction.get(r)
                    actions.append(_Action(r, d, "shortened", names=items))
                used = True
            elif len(items) >= 2 and _looks_like_streets(items):
                used = True   # a diversion path by streets; the stops come in the next sentences
                for r in st.lines:
                    actions.append(_Action(r, st.direction.get(r), "rerouted"))
            elif len(items) >= 2 and rids:
                both = bool(_BOTH_DIRS.search(f))
                for r in rids:
                    d = None if both else st.direction.get(r)
                    actions.append(_Action(r, d, "shortened", names=items))
                used = True

        # diverted without stop names
        if _REROUTE.search(f) and st.lines and not (sm or vm or rm) and not _NOT_A_CLOSURE.search(f):
            for r in st.lines:
                actions.append(_Action(r, st.direction.get(r), "rerouted"))
            used = True

        # the closed street: the first sentence that talks about works and names a street
        if geom is None and not closure_streets and _CLOSURE_KW.search(f):
            found = streets_in(sent)
            if found:
                geom, closure_streets, section, tram = _closure_geometry(sent, found)
                used = True

        if not used and (rids or streets_in(sent)) and not _NOT_A_CLOSURE.search(f):
            used = True
        if used and rids and _NOT_A_CLOSURE.search(f) and len(actions) == n_actions:
            used = False   # „Linia M30 – Traseul va fi prelungit …”: named, but nothing we can map
        if not used and not _COURTESY.search(f):
            unread.append(sent)

    # temporary routes: resolve and chain the streets
    temps: list[TemporaryRoute] = []
    for t in temp.values():
        resolved = [resolve_street(s) for s in t.streets]
        line = None
        try:
            hint = _end_hint(resolved[-1] if resolved else None, actions)
            ok = [s for s in resolved if s is not None]
            line = chain_streets(ok, hint) if len(ok) >= 2 else None
        except FileNotFoundError:
            line = None
        temps.append(TemporaryRoute(shortName=t.shortName, mode=t.mode, streets=t.streets, stopIds=None,
                                    geometry=to_geojson(line) if line is not None else None))

    route_actions: list[RouteAction] = []
    for a in _merge_actions(actions):
        route_actions += _expand(a)

    if window is None:
        start = local_midnight(ref.date())
        window = WindowFound(start, open_end_default(), True)

    cause = infer_cause(text)
    title = _title(closure_streets, route_ids, temps, window)
    direction = "both"
    closure = Closure(
        id="cl_parsed",
        status="draft",
        createdAt=iso(now()),
        title=title,
        kind="notice",
        geometry=to_geojson(geom) if geom is not None and not geom.is_empty else None,
        bufferMeters=30,
        direction=direction,
        window={"start": iso(window.start), "end": iso(window.end)},
        routeIds=route_ids or None,
        sourceText=text,
        sourceUrl=None,
        routeActions=route_actions if (route_actions or route_ids) else None,
        temporaryRoutes=temps or None,
    )
    if "ambele sensuri" in whole:
        closure = closure.model_copy(update={"direction": "both"})
    return ParseDetail(closure=closure, unread=unread, window=window, closure_streets=closure_streets,
                       section=section, tram=tram, lines_unknown=unknown_lines, cause=cause)


def _end_hint(last: Street | None, actions: list[_Action]) -> tuple[float, float] | None:
    """Where a temporary line ends on its last street: the stop on that street of a line it replaces."""
    if last is None:
        return None
    words = [w for w in norm(last.name).split() if w not in STREET_TYPES]
    if not words:
        return None
    net = load_network()
    replaced = {a.route_id for a in actions if a.action in ("suspended", "shortened")}
    cands = []
    for s in net.stops:
        toks = _tokens(s["name"])
        if all(w in toks for w in words):
            cands.append((0 if replaced & set(s.get("routeIds") or []) else 1, s["id"], s["location"]))
    if not cands:
        return None
    cands.sort()
    lon, lat = cands[0][2]
    return (lon, lat)


def _title(streets: list[Street], route_ids: list[str], temps: list[TemporaryRoute], w: WindowFound) -> I18n:
    net = load_network()
    shorts = [net.route_by_id[r]["shortName"] for r in route_ids if r in net.route_by_id]
    where = streets[0].name if streets else None
    day = w.start.strftime("%d.%m.%Y")
    ro, en = "Anunț STPT", "STPT notice"
    if where:
        ro += f": {where}"
        en += f": {where}"
    if shorts:
        ro += f" · {'linia' if len(shorts) == 1 else 'liniile'} {', '.join(shorts)}"
        en += f" · {'line' if len(shorts) == 1 else 'lines'} {', '.join(shorts)}"
    ro += f" · din {day}"
    en += f" · from {day}"
    return I18n(ro=ro, en=en)


def parse_notice(text: str, reference: datetime | None = None) -> ParseResult:
    """POST /api/closures/parse without saving: {closure, unread}. `reference` = date for „de mâine”."""
    d = parse_detail(text, reference)
    return ParseResult(closure=d.closure, unread=d.unread)


def mode_of(route_id: str) -> str:
    return route_mode(route_id)
