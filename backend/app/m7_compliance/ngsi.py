"""NGSI-LD export of the published alerts: GET /api/feed/alerts.ngsi.json (fix ticket T7-C).

The same alerts as /api/feed/alerts.pb (GTFS-RT), as FIWARE Smart Data Models entities, so a
city data platform that speaks NGSI-LD (e.g. an Orion-LD context broker, POST
/ngsi-ld/v1/entityOperations/upsert) can take them next to its own GtfsStop files:

  - one `Alert` (dataModel.Alert) per published alert that has not ended at "now": category
    `traffic`, subCategory `roadWorks` (works and track maintenance) or `roadClosed`, alertSource
    = the STPT notice when there is one, dateIssued = the publish time, validFrom / validTo = the
    alert's active period, location = the stop (per-stop alert) or the closed section (line-level
    alert); `refGtfsStop` points at the stop; the GTFS-RT cause, effect and lines go in `data`;
  - one `GtfsStop` (dataModel.UrbanMobility) per stop the alerts name: name, code, location.

Normalized NGSI-LD, one JSON array, each entity with its own @context. Text is Romanian (the
English text stays in the GTFS-RT feed). Times are ISO 8601 UTC, as dataModel.Alert asks.
Coordinates are GeoJSON, [longitude, latitude] (RFC 7946, which an NGSI-LD GeoProperty requires).
The city's own NGSI-LD traffic files store [lat, lng] inside a GeoJSON Point; we do not copy that.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app import config
from app.common import state
from app.common.city import load_network
from app.common.timeutil import iso, parse_iso
from app.m1_disruption.publish import published_alerts
from app.models.v1 import Alert

CORE_CONTEXT = "https://uri.etsi.org/ngsi-ld/v1/ngsi-ld-core-context.jsonld"
ALERT_CONTEXT = "https://raw.githubusercontent.com/smart-data-models/dataModel.Alert/master/context.jsonld"
MOBILITY_CONTEXT = "https://raw.githubusercontent.com/smart-data-models/dataModel.UrbanMobility/master/context.jsonld"
CONTEXT = [ALERT_CONTEXT, MOBILITY_CONTEXT, CORE_CONTEXT]

WORKS_CAUSES = ("CONSTRUCTION", "MAINTENANCE")
MEDIA_TYPE = "application/ld+json"


def alert_urn(alert_id: str) -> str:
    return f"urn:ngsi-ld:Alert:ReteauaVie:{alert_id}"


def stop_urn(stop_id: str) -> str:
    return f"urn:ngsi-ld:GtfsStop:SMTT:{stop_id}"


def utc(value: str) -> str:
    """'2026-11-08T10:00:00+02:00' -> '2026-11-08T08:00:00Z'."""
    return parse_iso(value).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _prop(value) -> dict:
    return {"type": "Property", "value": value}


def _time(value: str) -> dict:
    return {"type": "Property", "value": {"@type": "DateTime", "@value": utc(value)}}


def _point(lon: float, lat: float) -> dict:
    return {"type": "GeoProperty", "value": {"type": "Point", "coordinates": [lon, lat]}}


def _stop_ids(alert: Alert) -> list[str]:
    return list(dict.fromkeys(e.stopId for e in alert.informedEntity if e.stopId))


def alert_entity(alert: Alert, closure: dict, published_at: str | None, stops: dict[str, dict]) -> dict:
    stop_ids = _stop_ids(alert)
    starts = [p.start for p in alert.activePeriod]
    ends = [p.end for p in alert.activePeriod]
    source = closure.get("sourceUrl") or config.get_settings().public_base_url
    entity: dict = {
        "id": alert_urn(alert.id),
        "type": "Alert",
        "category": _prop("traffic"),
        "subCategory": _prop("roadWorks" if alert.cause in WORKS_CAUSES else "roadClosed"),
        "alertSource": _prop(source),
        "dateIssued": _time(published_at or (min(starts, key=parse_iso) if starts else iso(config.now()))),
        "name": _prop(alert.headerText.ro),
        "description": _prop(alert.descriptionText.ro),
        "seeAlso": _prop([u for u in (alert.url, closure.get("sourceUrl")) if u]),
        "data": _prop({
            "closureId": alert.closureId,
            "gtfsRtAlertId": alert.id,
            "gtfsRtCause": alert.cause,
            "gtfsRtEffect": alert.effect,
            "routeIds": sorted({e.routeId for e in alert.informedEntity if e.routeId}),
            "stopIds": stop_ids,
        }),
        "@context": CONTEXT,
    }
    if starts:
        entity["validFrom"] = _time(min(starts, key=parse_iso))
        entity["validTo"] = _time(max(ends, key=parse_iso))
    if len(stop_ids) == 1 and stop_ids[0] in stops:
        s = stops[stop_ids[0]]
        entity["location"] = _point(s["lon"], s["lat"])
        entity["refGtfsStop"] = {"type": "Relationship", "object": stop_urn(stop_ids[0])}
    elif closure.get("geometry"):
        entity["location"] = {"type": "GeoProperty", "value": closure["geometry"]}   # GeoJSON, [lon, lat]
    return entity


def stop_entity(stop: dict) -> dict:
    out = {
        "id": stop_urn(stop["id"]),
        "type": "GtfsStop",
        "name": _prop(stop["name"]),
        "location": _point(stop["lon"], stop["lat"]),
        "@context": CONTEXT,
    }
    if stop.get("code"):
        out["code"] = _prop(str(stop["code"]))
    return out


def entities(at: datetime | None = None) -> list[dict]:
    """Alert entities of every alert not ended at `at` (default: now), then their GtfsStop entities."""
    at = at or config.now()
    stops = load_network().stop_by_id
    closures: dict[str, dict] = {}
    published: dict[str, str | None] = {}
    alerts, stop_ids = [], []
    for alert in published_alerts(at):
        cid = alert.closureId
        if cid not in closures:
            closures[cid] = state.read("closures", cid) or {}
            published[cid] = (state.read("published", cid) or {}).get("publishedAt")
        alerts.append(alert_entity(alert, closures[cid], published[cid], stops))
        stop_ids += [s for s in _stop_ids(alert) if s in stops]
    return alerts + [stop_entity(stops[s]) for s in dict.fromkeys(stop_ids)]
