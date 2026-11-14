"""R3: the read-only functions Timi (the City Hall's assistant) may call. Static declarations in
JSON Schema, Romanian descriptions; `live` is computed from the routes this server really has, so
a function whose endpoint is not built yet is marked and the caller can skip it. No chat, no LLM here."""

from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI

from app.common.provenance import provenance
from app.config import now
from app.models.base import Provenance

AT = {"type": "string", "format": "date-time",
      "description": "Momentul întrebării, ISO 8601 cu fusul orar (de ex. 2026-11-08T12:00:00+02:00). Lipsă: acum."}


def _schema(props: dict[str, Any], required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_stop_status",
        "description": ("Spune de ce o stație nu este deservită sau care linii opresc la ea: liniile care opresc și cele "
                        "care nu opresc acum (pe sens), motivul (lucrările și anunțul STPT), cea mai apropiată stație "
                        "deservită și o propoziție gata scrisă în română și engleză. Folosește-o la întrebări ca "
                        "„de ce nu vine 4 la stația asta?”. Răspunsul vine din datele confirmate, nu din presupuneri."),
        "http": {"method": "GET", "path": "/api/stops/{stopId}/status", "pathParams": ["stopId"], "queryParams": ["at"]},
        "parameters": _schema({
            "stopId": {"type": "string", "description": "Identificatorul stației din GTFS-ul SMTT (de ex. „356”)."},
            "at": AT}, ["stopId"]),
        "lookup": {"path": "/api/stops/search", "queryParams": ["q", "lat", "lon", "radius"],
                   "description": "Găsește stația după nume (fără diacritice) sau în jurul unui punct, ca să obții stopId."},
        "answerField": "sentence",
        "path": "/api/stops/{stopId}/status",
    },
    {
        "name": "get_line_status",
        "description": ("Starea unei linii sau a tuturor liniilor: normală, deviată, scurtată, suspendată sau linie "
                        "temporară, cu perioada, anunțul STPT și linia care o înlocuiește. Cu `since` returnează doar ce "
                        "s-a schimbat de atunci. Folosește-o la întrebări ca „circulă linia 4?”."),
        "http": {"method": "GET", "path": "/api/lines/status", "pathParams": [], "queryParams": ["at", "routeId", "since"]},
        "parameters": _schema({
            "at": AT,
            "routeId": {"type": "string", "description": "Identificatorul liniei din GTFS (de ex. „R_TV_4”). Lipsă: toate liniile."},
            "since": {"type": "string", "format": "date-time", "description": "Returnează doar schimbările de la acest moment."}}, []),
        "answerField": None,
        "path": "/api/lines/status",
    },
    {
        "name": "plan_route",
        "description": ("Planifică un drum cu transportul public între două puncte, ocolind stațiile suspendate. Dă "
                        "coordonatele ca „lon,lat” în Timișoara. Poate răspunde 202 cu un jobId: se reia GET "
                        "/api/jobs/{jobId} până e gata. Nu promite trasee fără bariere: datele nu au acest câmp."),
        "http": {"method": "GET", "path": "/api/route", "pathParams": [], "queryParams": ["from", "to", "at"]},
        "parameters": _schema({
            "from": {"type": "string", "pattern": r"^-?\d+(\.\d+)?,-?\d+(\.\d+)?$", "description": "Plecarea, „lon,lat” (de ex. „21.2271,45.7489”)."},
            "to": {"type": "string", "pattern": r"^-?\d+(\.\d+)?,-?\d+(\.\d+)?$", "description": "Destinația, „lon,lat”."},
            "at": AT}, ["from", "to"]),
        "answerField": None,
        "path": "/api/route",
    },
    {
        "name": "get_notices",
        "description": ("Anunțurile pe cartiere ale lucrărilor publicate care sunt în curs: stradă, perioadă, stații și "
                        "linii afectate, în română și engleză. Filtrează după `zoneSlug` (cartierul) în răspuns. Folosește-o "
                        "la întrebări ca „ce lucrări sunt în Iosefin?”."),
        "http": {"method": "GET", "path": "/api/feed/notices.json", "pathParams": [], "queryParams": []},
        "parameters": _schema({}, []),
        "answerField": None,
        "path": "/api/feed/notices.json",
    },
]


def _has_get(app: FastAPI, path: str) -> bool:
    def plain(p: str) -> str:
        return re.sub(r"\{[^}]*\}", "{}", p)   # {stop_id} and {stopId} are the same route

    return any("get" in ops for p, ops in app.openapi().get("paths", {}).items() if plain(p) == plain(path))


def build(app: FastAPI) -> dict:
    tools = []
    for t in TOOLS:
        live = _has_get(app, t["path"])
        d = {k: v for k, v in t.items() if k != "path"}
        d["live"] = live
        d["note"] = None if live else "încă nu răspunde pe acest server: sari peste funcție până apare"
        tools.append(d)
    prov: Provenance = provenance("Rețeaua Vie: declarații generate din rutele serverului", now(), None, None,
                                  "doar citire (GET); fără chat și fără model de limbaj")
    return {"version": 1, "readOnly": True, "audience": "Timi",
            "description": "Funcții doar pentru citire, pe care asistentul Primăriei le poate apela. "
                           "Rețeaua Vie nu oferă chat.",
            "tools": tools, "provenance": [prov.model_dump()]}
