"""DATEX II v3 SituationPublication of the published closures (SPEC §6.1 item 13).

One `Situation` per published closure whose window has not ended at "now" (the same
rule as the GTFS-RT feed). Each LineString of the closure geometry becomes one
`RoadOrCarriagewayOrLaneManagement` record (cause from the closure: roadMaintenance for
track and equipment works, constructionWork for roadworks), validity = the closure window,
location = a WGS84 GML line string (`posList` in "lat lon" order, EPSG:4326).

Namespaces, element names and order follow the official DATEX II 3.5 XSD
(docs.datex2.eu); tests/test_m7_datex.py validates the output against it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from lxml import etree

from app import config
from app.common import state
from app.common.geo import from_geojson
from app.common.timeutil import iso, parse_iso

NS = {
    "d2": "http://datex2.eu/schema/3/d2Payload",
    "com": "http://datex2.eu/schema/3/common",
    "sit": "http://datex2.eu/schema/3/situation",
    "loc": "http://datex2.eu/schema/3/locationReferencing",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}
XSD_VERSION = "3.5"
PUBLISHER = "Rețeaua Vie (demo, UniHack 8)"
FEED_TYPE = "Rețeaua Vie: închideri și lucrări / closures and roadworks"
MAX_TEXT = 1024   # com:MultilingualStringValueType maxLength

# GTFS-RT cause (the closure's alert cause) -> DATEX II CauseTypeEnum
CAUSE = {"MAINTENANCE": "roadMaintenance", "CONSTRUCTION": "constructionWork"}


def _q(prefix: str, name: str) -> str:
    return f"{{{NS[prefix]}}}{name}"


def _sub(parent: etree._Element, prefix: str, name: str, text: str | None = None, **attrs) -> etree._Element:
    el = etree.SubElement(parent, _q(prefix, name), **attrs)
    if text is not None:
        el.text = text
    return el


def _multilingual(parent: etree._Element, prefix: str, name: str, texts: dict) -> etree._Element:
    el = _sub(parent, prefix, name)
    values = _sub(el, "com", "values")
    for lang in ("ro", "en"):
        t = (texts or {}).get(lang)
        if t:
            _sub(values, "com", "value", t[:MAX_TEXT], lang=lang)
    return el


def _xsi_type(prefix: str, name: str) -> dict:
    return {_q("xsi", "type"): f"{prefix}:{name}"}


@dataclass(frozen=True)
class PublishedClosure:
    closure: dict
    published_at: str


def published_closures(at: datetime | None = None, active_only: bool = True) -> list[PublishedClosure]:
    """Published closures from the state store; with active_only, those whose window has not ended at `at`."""
    at = at or config.now()
    out = []
    for pub in state.list_all("published"):
        cid = pub.get("closureId")
        closure = state.read("closures", cid) if cid else None
        if closure is None:
            continue
        if active_only and parse_iso(closure["window"]["end"]) <= at:
            continue
        out.append(PublishedClosure(closure, pub.get("publishedAt") or iso(at)))
    return sorted(out, key=lambda p: (p.closure["window"]["start"], p.closure["id"]))


def _lines(geometry: dict | None) -> list[list[tuple[float, float]]]:
    """The closure geometry as lists of (lon, lat); points-only or empty geometry gives []."""
    if not geometry:
        return []
    g = from_geojson(geometry)
    parts = list(getattr(g, "geoms", [g]))
    return [[(float(x), float(y)) for x, y, *_ in p.coords] for p in parts
            if p.geom_type == "LineString" and len(p.coords) >= 2]


def _cause(closure: dict) -> str:
    from app.m1_disruption.alerts import alert_cause

    return CAUSE.get(alert_cause(closure), "other")


def _record(situation: etree._Element, closure: dict, part_no: int, coords: list[tuple[float, float]],
            published_at: str, at: datetime) -> None:
    rec = _sub(situation, "sit", "situationRecord", id=f"{closure['id']}_r{part_no}", version="1",
               **_xsi_type("sit", "RoadOrCarriagewayOrLaneManagement"))
    _sub(rec, "sit", "situationRecordCreationTime", published_at)
    _sub(rec, "sit", "situationRecordVersionTime", published_at)
    _sub(rec, "sit", "probabilityOfOccurrence", "certain")
    validity = _sub(rec, "sit", "validity")
    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    _sub(validity, "com", "validityStatus", "active" if start <= at < end else "definedByValidityTimeSpec")
    spec = _sub(validity, "com", "validityTimeSpecification")
    _sub(spec, "com", "overallStartTime", iso(start))
    _sub(spec, "com", "overallEndTime", iso(end))
    cause = _sub(rec, "sit", "cause")
    _sub(cause, "sit", "causeType", _cause(closure))
    title = closure.get("title") or {}
    if title.get("ro"):
        comment = _sub(rec, "sit", "generalPublicComment")
        _multilingual(comment, "sit", "comment", title)
    note = closure.get("locationNote")
    if note and note.get("ro"):
        comment = _sub(rec, "sit", "generalPublicComment")
        _multilingual(comment, "sit", "comment", note)
    if closure.get("sourceUrl"):
        link = _sub(rec, "sit", "urlLink")
        _sub(link, "com", "urlLinkAddress", closure["sourceUrl"])
        _multilingual(link, "com", "urlLinkDescription", {"ro": "Anunțul STPT", "en": "The STPT notice"})
    loc = _sub(rec, "sit", "locationReference", **_xsi_type("loc", "LinearLocation"))
    gml = _sub(loc, "loc", "gmlLineString", srsDimension="2", srsName="EPSG:4326")
    _sub(gml, "loc", "posList", " ".join(f"{lat:.6f} {lon:.6f}" for lon, lat in coords))
    _sub(rec, "sit", "complianceOption", "mandatory")
    kind = "roadClosed" if closure.get("direction", "both") == "both" else "carriagewayClosures"
    _sub(rec, "sit", "roadOrCarriagewayOrLaneManagementType", kind)


def build_publication(items: list[PublishedClosure], at: datetime) -> tuple[etree._Element, list[str]]:
    """The d2:payload element and the ids of closures left out (no line geometry)."""
    root = etree.Element(_q("d2", "payload"), nsmap={k: v for k, v in NS.items()}, lang="ro",
                         modelBaseVersion="3", **_xsi_type("sit", "SituationPublication"))
    _multilingual(root, "com", "feedDescription", {
        "ro": "Închideri și lucrări publicate prin Rețeaua Vie (demo, UniHack 8). Nu este un flux oficial "
              "al Primăriei Timișoara sau al STPT.",
        "en": "Closures and roadworks published through Rețeaua Vie (demo, UniHack 8). Not an official "
              "feed of Timișoara City Hall or STPT.",
    })
    _sub(root, "com", "feedType", FEED_TYPE)
    _sub(root, "com", "publicationTime", iso(at))
    creator = _sub(root, "com", "publicationCreator")
    _sub(creator, "com", "country", "ro")
    _sub(creator, "com", "nationalIdentifier", PUBLISHER)
    skipped = []
    for item in items:
        lines = _lines(item.closure.get("geometry"))
        if not lines:
            skipped.append(item.closure["id"])
            continue
        situation = _sub(root, "sit", "situation", id=item.closure["id"])
        _sub(situation, "sit", "situationVersionTime", item.published_at)
        header = _sub(situation, "sit", "headerInformation")
        _sub(header, "com", "confidentiality", "noRestriction")
        _sub(header, "com", "informationStatus", "real")
        for n, coords in enumerate(lines, start=1):
            _record(situation, item.closure, n, coords, item.published_at, at)
    if skipped:
        root.append(etree.Comment(" fără geometrie / no line geometry: " + ", ".join(skipped) + " "))
    return root, skipped


def to_bytes(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def feed_xml(at: datetime | None = None) -> bytes:
    """GET /api/feed/datex.xml: every published closure that has not ended at `at`."""
    at = at or config.now()
    root, _skipped = build_publication(published_closures(at), at)
    return to_bytes(root)
