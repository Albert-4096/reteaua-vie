"""The files we publish (GET /api/exports) and their NAP metadata (GET /api/exports/nap-metadata.json).

An export is listed only when its route is mounted in the running API, so the list (and the
compliance `coveredBy`, which is computed from it) never names a file we do not serve.
The NAP metadata is one mobilityDCAT-AP JSON-LD `dcat:Catalog` with four datasets (SPEC §6.7):
alerts.pb, datex.xml, notices.json and history.json. The publisher is Rețeaua Vie as a demo;
it never claims to be STPT or the City Hall.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from app import config
from app.common import state
from app.common.timeutil import iso, parse_iso
from app.models.v2 import ExportFile

PUBLISHER_NAME = "Rețeaua Vie (demo, UniHack 8)"
NOT_OFFICIAL = {
    "ro": "Demonstrație realizată la UniHack 8. Nu este un set de date oficial al Primăriei Timișoara sau al STPT.",
    "en": "Demonstration built at UniHack 8. Not an official dataset of Timișoara City Hall or STPT.",
}


@dataclass(frozen=True)
class ExportSpec:
    name: str
    path: str                  # API path, without the /api prefix
    format: str                # ExportFile.format
    standard: str
    media_type: str
    title_ro: str
    title_en: str
    desc_ro: str
    desc_en: str
    nap: bool                  # one of the four NAP datasets
    conforms_to: str | None    # URL of the standard


EXPORTS: tuple[ExportSpec, ...] = (
    ExportSpec("alerts.pb", "/feed/alerts.pb", "GTFS-RT", "GTFS Realtime 2.0, ServiceAlert (FULL_DATASET)",
               "application/x-protobuf", "Alerte de transport public (GTFS-RT)", "Public transport alerts (GTFS-RT)",
               "Stațiile și liniile afectate de lucrări, pe linie, stație și sens, cu textul în română și engleză.",
               "Stops and lines affected by works, per line, stop and direction, with Romanian and English text.",
               True, "https://gtfs.org/documentation/realtime/reference/"),
    ExportSpec("alerts.json", "/feed/alerts.json", "JSON", "GTFS Realtime 2.0 Alert, JSON view (Rețeaua Vie)",
               "application/json", "Alerte (vedere JSON)", "Alerts (JSON view)",
               "Aceleași alerte ca alerts.pb, în JSON.", "The same alerts as alerts.pb, as JSON.",
               False, None),
    ExportSpec("alerts.ngsi.json", "/feed/alerts.ngsi.json", "NGSI-LD",
               "NGSI-LD, FIWARE Smart Data Models Alert + GtfsStop", "application/ld+json",
               "Alerte pentru platforma de date a orașului (NGSI-LD)", "Alerts for the city data platform (NGSI-LD)",
               "Aceleași alerte ca alerts.pb, ca entități FIWARE Alert și GtfsStop; coordonate GeoJSON [lng, lat].",
               "The same alerts as alerts.pb, as FIWARE Alert and GtfsStop entities; GeoJSON [lng, lat] coordinates.",
               False, "https://smartdatamodels.org/"),
    ExportSpec("datex.xml", "/feed/datex.xml", "DATEX II", "DATEX II v3.5, SituationPublication",
               "application/xml", "Închideri și lucrări (DATEX II)", "Closures and roadworks (DATEX II)",
               "Închiderile publicate, cu fereastra de timp și traseul închis (WGS84).",
               "The published closures, with their time window and closed section (WGS84).",
               True, "https://docs.datex2.eu/"),
    ExportSpec("notices.json", "/feed/notices.json", "JSON", "Rețeaua Vie ZoneNotice[] (anunțuri pe cartier)",
               "application/json", "Anunțuri pe cartier", "Neighbourhood notices",
               "Un anunț pe cartier atins de o lucrare publicată: străzi, linii, stații, cea mai apropiată stație.",
               "One notice per neighbourhood hit by a published closure: streets, lines, stops, nearest stop.",
               True, None),
    ExportSpec("history.json", "/history", "JSON", "Rețeaua Vie HistoryEntry[] (istoricul perturbărilor, MMTIS)",
               "application/json", "Istoricul perturbărilor", "Disruption history",
               "Lucrările publicate prin platformă și cele reconstituite din anunțurile STPT (marcate).",
               "Closures published through the platform and those reconstructed from STPT notices (labelled).",
               True, None),
    ExportSpec("indicators.json", "/indicators", "JSON", "Rețeaua Vie IndicatorSet (indicatori PMUD / TEN-T)",
               "application/json", "Indicatori de mobilitate", "Mobility indicators",
               "Indicatorii pe care îi putem calcula din date publice, fiecare cu metoda lui.",
               "The indicators we can compute from public data, each with its method.",
               False, None),
    ExportSpec("nap-metadata.json", "/exports/nap-metadata.json", "mobilityDCAT-AP",
               "mobilityDCAT-AP 1.0 (JSON-LD, dcat:Catalog)", "application/ld+json",
               "Metadate pentru punctul național de acces", "National Access Point metadata",
               "Catalogul seturilor de date de mai sus, pentru punctul național de acces.",
               "The catalogue of the datasets above, for the National Access Point.",
               False, "https://mobilitydcat-ap.github.io/mobilityDCAT-AP/releases/"),
)


def base_url() -> str:
    return config.get_settings().public_base_url


def url_of(spec: ExportSpec) -> str:
    return f"{base_url()}/api{spec.path}"


def mounted_paths() -> set[str]:
    """Paths (with /api) of every route the running API mounted from its router modules."""
    import importlib

    from app import main

    out = set()
    for name in main.ROUTER_MODULES:
        router = getattr(importlib.import_module(name), "router", None)
        for route in getattr(router, "routes", ()):
            path = getattr(route, "path", None)
            if path:
                out.add(f"/api{path}")
    return out


def available(mounted_paths: Iterable[str]) -> list[ExportSpec]:
    """The exports whose API route is mounted (paths as FastAPI lists them, with /api)."""
    mounted = set(mounted_paths)
    return [e for e in EXPORTS if f"/api{e.path}" in mounted]


def last_publish() -> str | None:
    """The newest publishedAt of the published closures, or None when nothing is published."""
    times = [p["publishedAt"] for p in state.list_all("published") if p.get("publishedAt")]
    return max(times, key=parse_iso) if times else None


def export_files(mounted_paths: Iterable[str]) -> list[ExportFile]:
    """GET /api/exports. updatedAt = the last publish for the feeds; null when nothing is published."""
    updated = last_publish()
    return [ExportFile(name=e.name, format=e.format, standard=e.standard, url=url_of(e), updatedAt=updated)
            for e in available(mounted_paths)]


# --- mobilityDCAT-AP ------------------------------------------------------------------------------

CONTEXT = {
    "dcat": "http://www.w3.org/ns/dcat#",
    "dct": "http://purl.org/dc/terms/",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "mobilitydcatap": "https://w3id.org/mobilitydcat-ap#",
    "adms": "http://www.w3.org/ns/adms#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "vcard": "http://www.w3.org/2006/vcard/ns#",
}
EU_VOCAB = "http://publications.europa.eu/resource/authority"
MOBILITY_THEME = "https://w3id.org/mobilitydcat-ap/mobility-theme"
FORMAT_VOCAB = "https://w3id.org/mobilitydcat-ap/mobility-data-standard"
TRANSPORT_MODE = "https://w3id.org/mobilitydcat-ap/transport-mode"
# mobilityDCAT-AP controlled vocabularies (https://w3id.org/mobilitydcat-ap/<vocabulary>, read 13 Nov 2026)
THEME = {"alerts.pb": "disruptions-delays-cancellations", "datex.xml": "road-closures-and-access-conditions",
         "notices.json": "disruptions-delays-cancellations", "history.json": "disruptions-delays-cancellations"}
STANDARD = {"alerts.pb": "gtfs-rt", "datex.xml": "datex-II", "notices.json": "other", "history.json": "other"}
TRANSPORT_MODES = ("bus", "tram-light-rail")   # the vocabulary has no trolleybus; it is a road bus mode
TIMISOARA_GEONAMES = "https://sws.geonames.org/665087/"


def _lit(text: str, lang: str) -> dict:
    return {"@value": text, "@language": lang}


def nap_metadata(mounted_paths: Iterable[str], at: datetime | None = None) -> dict:
    """One dcat:Catalog (JSON-LD) with the four NAP datasets that are served right now."""
    at = at or config.now()
    base = base_url()
    updated = last_publish()
    publisher = {
        "@id": f"{base}/#publisher",
        "@type": "foaf:Agent",
        "foaf:name": PUBLISHER_NAME,
        "dct:description": [_lit(NOT_OFFICIAL["ro"], "ro"), _lit(NOT_OFFICIAL["en"], "en")],
    }
    datasets = []
    for e in available(mounted_paths):
        if not e.nap:
            continue
        url = url_of(e)
        dist = {
            "@id": f"{url}#distribution",
            "@type": "dcat:Distribution",
            "dcat:accessURL": {"@id": url},
            "dcat:downloadURL": {"@id": url},
            "dcat:mediaType": e.media_type,
            "mobilitydcatap:mobilityDataStandard": {"@id": f"{FORMAT_VOCAB}/{STANDARD[e.name]}"},
            "dct:description": _lit(e.standard, "en"),
        }
        if e.conforms_to:
            dist["dct:conformsTo"] = {"@id": e.conforms_to}
        ds = {
            "@id": f"{url}#dataset",
            "@type": "dcat:Dataset",
            "dct:identifier": e.name,
            "dct:title": [_lit(e.title_ro, "ro"), _lit(e.title_en, "en")],
            "dct:description": [_lit(e.desc_ro + " " + NOT_OFFICIAL["ro"], "ro"),
                                _lit(e.desc_en + " " + NOT_OFFICIAL["en"], "en")],
            "dct:publisher": {"@id": publisher["@id"]},
            "dct:spatial": {"@id": TIMISOARA_GEONAMES},
            "dct:language": [{"@id": f"{EU_VOCAB}/language/RON"}, {"@id": f"{EU_VOCAB}/language/ENG"}],
            "dct:accrualPeriodicity": {"@id": f"{EU_VOCAB}/frequency/IRREG"},
            "mobilitydcatap:mobilityTheme": {"@id": f"{MOBILITY_THEME}/{THEME[e.name]}"},
            "mobilitydcatap:transportMode": [{"@id": f"{TRANSPORT_MODE}/{m}"} for m in TRANSPORT_MODES],
            "dcat:distribution": [dist],
        }
        if updated:
            ds["dct:modified"] = {"@value": updated, "@type": "xsd:dateTime"}
        datasets.append(ds)
    records = [{
        "@id": f"{ds['@id']}-record",
        "@type": "dcat:CatalogRecord",
        "foaf:primaryTopic": {"@id": ds["@id"]},
        "dct:created": {"@value": iso(at), "@type": "xsd:dateTime"},
        "dct:modified": ds.get("dct:modified") or {"@value": iso(at), "@type": "xsd:dateTime"},
        "dct:language": {"@id": f"{EU_VOCAB}/language/ENG"},
    } for ds in datasets]
    return {
        "@context": CONTEXT,
        "@id": f"{base}/api/exports/nap-metadata.json",
        "@type": "dcat:Catalog",
        "dct:title": [_lit("Rețeaua Vie: perturbări în transportul public din Timișoara (demo)", "ro"),
                      _lit("Rețeaua Vie: public transport disruptions in Timișoara (demo)", "en")],
        "dct:description": [_lit(NOT_OFFICIAL["ro"], "ro"), _lit(NOT_OFFICIAL["en"], "en")],
        "dct:publisher": publisher,
        "dct:issued": {"@value": iso(at), "@type": "xsd:dateTime"},
        "dct:spatial": {"@id": TIMISOARA_GEONAMES},
        "dct:language": [{"@id": f"{EU_VOCAB}/language/RON"}, {"@id": f"{EU_VOCAB}/language/ENG"}],
        "foaf:homepage": {"@id": base},
        "dcat:dataset": datasets,
        "dcat:record": records,
    }
