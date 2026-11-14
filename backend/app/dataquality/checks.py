"""R12: the gaps in the data the City Hall and SMTT publish, measured on request.

Everything is computed from files on disk (the GTFS in force, the OSM extract, the
City Hall parking file, the STPT notices, the newest recorded vehicle snapshot).
Wording is „de verificat”: we flag what we cannot confirm, never what is „greșit”.
The one `basis: "manual"` row is a dated observation of ours; the static-GTFS
validator of MobilityData is not on disk, so its row says so and nothing is downloaded.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from functools import lru_cache

import numpy as np

from app.common import gtfs, stpt_posts, vehicles
from app.common import provenance as prov
from app.common.city import _city_file, _read_json
from app.common.timeutil import iso
from app.config import get_settings, real_now
from app.dataquality.models import DataQuality, QualityRow
from app.models.base import I18n, Provenance

CAP = 15
OSM_FILE = "osm/timisoara.osm.pbf"
OSM_CACHE_VERSION = 1


def _row(id, ro, en, found, of, detail, owner, unlocks, request, provenance, basis="calculat", ok_if_zero=True,
         status=None) -> QualityRow:
    st = status or ("in_regula" if (ok_if_zero and found == 0) else "de_verificat")
    return QualityRow(id=id, title=I18n(ro=ro, en=en), status=st, basis=basis, found=found, of=of,
                      detail=detail[:CAP], owner=owner, unlocks=unlocks, request=request, provenance=provenance)


# --- one function per row ---------------------------------------------------------


def gtfs_wheelchair(f: gtfs.Feed) -> QualityRow:
    cols = set(f.stops.columns)
    n = len(f.stops)
    if "wheelchair_boarding" in cols:
        vals = f.stops["wheelchair_boarding"].astype(str).str.strip()
        missing = int((vals.isin(["", "0"])).sum())
    else:
        missing = n
    return _row(
        "gtfs_wheelchair", "Stații GTFS fără informație de accesibilitate (wheelchair_boarding)",
        "GTFS stops with no wheelchair_boarding value", missing, n,
        [] if not missing else [f"{missing} din {n} stații din feed-ul {f.version} nu au valoare (câmpul lipsește din stops.txt)"
                                 if "wheelchair_boarding" not in cols else f"{missing} din {n} stații au valoarea 0 sau goală"],
        "SMTT",
        I18n(ro="Ruta „fără bariere” pe stație, în loc de „date necunoscute”.", en="A step-free route per stop instead of „unknown”."),
        I18n(ro=(f"Bună ziua. În feed-ul GTFS {f.version} publicat de SMTT, fișierul stops.txt nu conține câmpul wheelchair_boarding "
                 f"({missing} din {n} stații). Este de verificat dacă SMTT poate publica accesibilitatea fiecărei stații, "
                 "ca aplicațiile să poată indica rute fără bariere. Mulțumim."),
             en=f"GTFS {f.version} stops.txt has no wheelchair_boarding for {missing} of {n} stops. Could SMTT publish it?"),
        [f.provenance],
    )


def _osm_stats() -> tuple[int, int, Provenance] | None:
    pbf = get_settings().data_dir / OSM_FILE
    if not pbf.is_file():
        return None
    st = pbf.stat()
    key = hashlib.sha1(f"{OSM_CACHE_VERSION}:{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()[:12]
    cache = get_settings().cache_dir / f"osm_bus_stop_wheelchair_v{OSM_CACHE_VERSION}_{key}.json"
    if cache.is_file():
        total, tagged = json.loads(cache.read_text(encoding="utf-8"))
    else:
        import pyrosm  # slow import, only when building the cache

        g = pyrosm.OSM(str(pbf)).get_data_by_custom_criteria(
            custom_filter={"highway": ["bus_stop"]}, filter_type="keep",
            keep_nodes=True, keep_ways=False, keep_relations=False)
        total = 0 if g is None else len(g)
        tagged = 0 if g is None else int(sum('"wheelchair"' in str(t) for t in g["tags"].tolist())
                                          + (int(g["wheelchair"].notna().sum()) if "wheelchair" in g else 0))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps([total, tagged]), encoding="utf-8")
    p = prov.for_file("OpenStreetMap (extras Geofabrik, local) / OSM extract", pbf, None, None, "highway=bus_stop, cheia wheelchair")
    return total, tagged, p


def osm_wheelchair() -> QualityRow:
    stats = _osm_stats()
    req = I18n(ro=("Bună ziua. În OpenStreetMap, stațiile de autobuz din Timișoara nu au eticheta wheelchair. Este de verificat dacă "
                   "SMTT sau Primăria poate transmite lista stațiilor accesibile, ca să fie adăugată în hartă și în aplicații."),
               en="Bus stops in OpenStreetMap carry no wheelchair tag. Could SMTT or the City Hall share the accessible-stop list?")
    unlocks = I18n(ro="Accesibilitatea pe stație, verificabilă pe hartă.", en="Per-stop accessibility, checkable on the map.")
    if stats is None:
        return _row("osm_wheelchair", "Stații OSM fără etichetă wheelchair", "OSM stops with no wheelchair tag", None, None,
                    ["Extractul OSM nu e pe disc."], "Primăria", unlocks, req, [], status="indisponibil")
    total, tagged, p = stats
    return _row("osm_wheelchair", "Stații OSM fără etichetă wheelchair", "OSM stops with no wheelchair tag", total - tagged, total,
                [f"{tagged} din {total} stații (highway=bus_stop) au eticheta wheelchair"], "Primăria", unlocks, req, [p])


def live_delay() -> QualityRow:
    snap = vehicles.newest_snapshot()
    unlocks = I18n(ro="Punctualitatea și întârzierea pe linie, pentru toate vehiculele.", en="Punctuality per line for every vehicle.")
    if snap is None:
        return _row("live_delay", "Vehicule live fără delaySec", "Live vehicles with no delaySec", None, None,
                    ["Nu există înregistrare de vehicule."], "Primăria", unlocks, I18n(ro="-", en=None), [], status="indisponibil")
    vs = snap.get("vehicles", [])
    miss = [v for v in vs if v.get("delaySec") is None]
    at = vehicles.snapshot_time(snap)
    routes = sorted({str(v.get("routeId")) for v in miss})
    return _row(
        "live_delay", "Vehicule live fără delaySec", "Live vehicles with no delaySec", len(miss), len(vs),
        [f"{len(miss)} din {len(vs)} vehicule fără delaySec în ultimul instantaneu ({iso(at)}); linii: {', '.join(routes[:12])}"] if miss else [],
        "Primăria", unlocks,
        I18n(ro=("Bună ziua. În API-ul de vehicule al Primăriei, câmpul delaySec lipsește pentru "
                 f"{len(miss)} din {len(vs)} vehicule în instantaneul din {iso(at)}. Este de verificat dacă lipsește din sursa GPS "
                 "sau din API. Mulțumim."), en=f"delaySec is missing for {len(miss)} of {len(vs)} vehicles."),
        [prov.vehicles_provenance(at, "ultimul instantaneu înregistrat")],
    )


def timpark_unchecked() -> QualityRow:
    path = _city_file("parking.json")
    feats = _read_json(path)["features"]
    unchecked = [x for x in feats if not x.get("checked")]
    kinds: dict[str, int] = defaultdict(int)
    for x in unchecked:
        kinds[x.get("kind", "?")] += 1
    return _row(
        "timpark_unchecked", "Elemente Timpark nemarcate ca verificate de Primărie", "Timpark features not marked as checked",
        len(unchecked), len(feats), [", ".join(f"{k}: {n}" for k, n in sorted(kinds.items()))] if unchecked else [],
        "Timpark",
        I18n(ro="Tarifele și locurile de parcare din analiza de impact, fără rezerve.", en="Parking tariffs and lots in the impact analysis without caveats."),
        I18n(ro=(f"Bună ziua. În datele de parcare ale Primăriei, {len(unchecked)} din {len(feats)} elemente au câmpul checked=false "
                 f"({', '.join(f'{k}: {n}' for k, n in sorted(kinds.items()))}). Este de verificat dacă tarifele și geometria lor sunt confirmate."),
             en="Parking features with checked=false."),
        [prov.for_file("Primăria Timișoara, parcări (API CityApp) / City Hall parking", path, prov.CITY_PARKING_URL)],
    )


_PLAUSIBLE = re.compile(r"^[a-z]{0,2}\d{1,3}[a-z]?$")


def _notice_tokens(text: str) -> list[str]:
    from app.m1_disruption.parser import line_tokens

    out = []
    for t in line_tokens(text):
        t = t.replace(" ", "")
        m = re.fullmatch(r"si(\d.*)", t)  # „și” folded and glued to the next token
        t = m.group(1) if m else t
        if _PLAUSIBLE.match(t):
            out.append(t)
    return out


def notice_lines_missing(f: gtfs.Feed) -> QualityRow:
    have = {re.sub(r"\s", "", s.lower()) for s in f.routes.route_short_name}
    named: dict[str, list[int]] = defaultdict(list)
    posts = stpt_posts.load_posts()
    for p in posts.values():
        for t in set(_notice_tokens(p.title + "\n" + p.text)):
            if t not in have:
                named[t].append(p.id)
    detail = [f"linia {t.upper()}: apare în anunțurile STPT {', '.join(str(i) for i in sorted(ids))}, dar nu în GTFS {f.version}"
              for t, ids in sorted(named.items())]
    lines = ", ".join(t.upper() for t in sorted(named))
    return _row(
        "notice_lines_not_in_gtfs", "Linii numite în anunțurile STPT, absente din GTFS", "Lines named in STPT notices but absent from GTFS",
        len(named), None, detail, "SMTT",
        I18n(ro="Anunțurile pot fi legate automat de linie, inclusiv pentru liniile temporare sau școlare.", en="Notices can be linked to their line automatically."),
        I18n(ro=(f"Bună ziua. Anunțurile STPT menționează liniile {lines or '-'}, care nu apar în route_short_name din feed-ul GTFS {f.version}. "
                 "Este de verificat dacă sunt linii temporare, școlare sau dacă lipsesc din feed."),
             en=f"STPT notices name lines {lines} that are not in GTFS {f.version}."),
        [f.provenance] + [p.provenance() for p in list(posts.values())[:1]],
        ok_if_zero=True,
    )


def menu_missing() -> QualityRow:
    p = Provenance(source="smtt.ro, pagina liniei și meniul de orare (verificat manual de echipă)", url="https://smtt.ro/linie-transport-public-23",
                   version=None, fetchedAt="2026-11-14T10:45:00+02:00",
                   note="Observație manuală, nu calculată: nu avem meniul SMTT pe disc și nu îl citim automat.")
    return _row(
        "smtt_menu_missing", "Linii cu pagină la SMTT, dar fără intrare în meniul de orare", "Lines with a SMTT page but no timetable-menu entry",
        1, None, ["linia 23 (Banatim (Garaj STPT) – Gara de Est): pagina există, meniul de orare al autobuzelor urbane nu o listează (verificat 14 nov 2026)"],
        "SMTT",
        I18n(ro="Orarul liniei 23 găsit de cetățeni în meniul oficial.", en="Line 23's timetable findable in the official menu."),
        I18n(ro=("Bună ziua. Pagina smtt.ro/linie-transport-public-23 există, dar meniul de orare al autobuzelor urbane nu listează linia 23 "
                 "(verificat la 14 nov 2026). Este de verificat dacă omisiunea este intenționată."),
             en="Line 23 has a page on smtt.ro but is not listed in the urban bus timetable menu (checked 14 Nov 2026)."),
        [p], basis="manual",
    )


def gtfs_structure(f: gtfs.Feed) -> QualityRow:
    st = f.stop_times
    used_stops = set(st.stop_id)
    stops = f.stops
    top = stops["location_type"].astype(str).isin(["", "0"]) if "location_type" in stops else np.ones(len(stops), bool)
    orphan = [f"{r.stop_id} {r.stop_name}" for r in stops[top & ~stops.stop_id.isin(used_stops)].itertuples()]
    no_trips = [f"{r.route_id} ({r.route_short_name})" for r in f.routes[~f.routes.route_id.isin(set(f.trips.route_id))].itertuples()]
    per_trip = st.groupby("trip_id").size()
    short = [t for t in f.trips.trip_id if per_trip.get(t, 0) < 2]
    s = st.sort_values(["trip_id", "stop_sequence"])
    back = s.groupby("trip_id")["dep_sec"].diff() < 0
    back_trips = sorted(set(s.loc[back, "trip_id"]))
    detail = []
    if orphan:
        detail.append(f"{len(orphan)} stații fără nicio oprire în stop_times: " + "; ".join(orphan[:5]))
    if no_trips:
        detail.append(f"{len(no_trips)} linii fără curse: " + ", ".join(no_trips[:8]))
    if short:
        detail.append(f"{len(short)} curse cu mai puțin de 2 opriri: " + ", ".join(short[:5]))
    if back_trips:
        detail.append(f"{len(back_trips)} curse cu ore care scad între opriri: " + ", ".join(back_trips[:5]))
    n = len(orphan) + len(no_trips) + len(short) + len(back_trips)
    return _row(
        "gtfs_structure", "Verificări simple de structură pe GTFS (ale noastre, nu MobilityData)", "Simple GTFS structure checks (ours, not MobilityData)",
        n, None, detail, "SMTT",
        I18n(ro="Un feed fără stații sau curse orfane pentru Google, CityApp și Punctul Național de Acces.", en="A feed free of orphan stops and trips."),
        I18n(ro=(f"Bună ziua. La o verificare simplă a feed-ului GTFS {f.version}: " + (" ".join(detail) if detail else "nimic de semnalat.")
                 + " Este de verificat dacă sunt intenționate."), en=f"Simple structure checks on GTFS {f.version}."),
        [f.provenance],
    )


def validator_row(f: gtfs.Feed) -> QualityRow:
    return _row(
        "mobilitydata_validator", "Raportul validatorului MobilityData pentru GTFS static", "MobilityData static GTFS validator report",
        None, None,
        ["Validatorul GTFS static nu este pe disc (doar cel pentru GTFS Realtime, în data/tools); nu l-am descărcat."],
        "SMTT",
        I18n(ro="Lista de erori și avertismente a unui validator recunoscut, atașată cererii către SMTT.", en="A recognised validator's error list for the SMTT request."),
        I18n(ro=f"Raport indisponibil: rulați validatorul MobilityData pe feed-ul GTFS {f.version} și atașați-l cererii.", en=None),
        [], status="indisponibil",
    )


def data_quality() -> DataQuality:
    f = gtfs.feed()
    rows = [gtfs_wheelchair(f), osm_wheelchair(), live_delay(), timpark_unchecked(), notice_lines_missing(f),
            menu_missing(), gtfs_structure(f), validator_row(f)]
    seen: dict[tuple, Provenance] = {}
    for r in rows:
        for p in r.provenance:
            seen[(p.source, p.version, p.fetchedAt)] = p
    return DataQuality(generatedAt=iso(real_now()), rows=rows, provenance=list(seen.values()))


def to_csv(dq: DataQuality) -> str:
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "titlu", "status", "bază", "găsite", "din", "detalii", "responsabil", "ce deblochează", "text cerere"])
    for r in dq.rows:
        w.writerow([r.id, r.title.ro, r.status, r.basis, "" if r.found is None else r.found, "" if r.of is None else r.of,
                    " | ".join(r.detail), r.owner, r.unlocks.ro, r.request.ro])
    return "﻿" + buf.getvalue()
