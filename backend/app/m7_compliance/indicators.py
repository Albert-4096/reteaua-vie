"""PMUD / TEN-T urban-node indicators we can compute honestly (SPEC §6.7): GET /api/indicators.

Every indicator carries its formula in `method`. What we cannot compute is `null`
(„necunoscut”), never 0. The indicators:
  STOPS_CITY, STOPS_CITY_SHARE      GTFS stops inside the 40 neighbourhoods, and their share of all GTFS stops
  RES_400M, RES_400M_SHARE          residents (GHSL 2020, model) within 400 m of a stop with scheduled service
  AC1_0700, AC1_1600, AC1_ANY       AC.1-style share of stops with >= 4 departures of one route in the hour
  BIKE_KM, BIKE_KM_LTS2             km of bike ways in the 40 neighbourhoods (OSM), total and LTS <= 2 (M5)
  PR_OPTIONS                        Park & Ride options (M6 rule)
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import shapely
from shapely.ops import unary_union

from app import config
from app.common import gtfs
from app.common.city import load_zones
from app.common.geo import project_lonlats
from app.common.timeutil import iso, local_midnight
from app.models.base import I18n, Provenance
from app.models.v2 import Indicator, IndicatorSet

log = logging.getLogger("reteaua_vie.m7.indicators")

INDICATORS_VERSION = 1
RADIUS_M = 400.0
AC1_MIN_DEPARTURES = 4
AC1_HOURS = (7, 16)
REFERENCE_WEEKDAY = 1   # Tuesday: a plain working day
SCOPE_CITY = "Timișoara, cele 40 de cartiere (/api/zones)"
SCOPE_NETWORK = "rețeaua SMTT: oraș + zona metropolitană (GTFS)"
GHSL_LABEL = "model GHSL 2020, nu recensământ"


def _stops() -> tuple[list[str], np.ndarray]:
    """GTFS stop ids (location_type 0 / empty) and their [lon, lat]."""
    s = gtfs.feed().stops
    if "location_type" in s.columns:
        s = s[s["location_type"].isin(["", "0"])]
    lonlat = np.column_stack([s["stop_lon"].astype(float), s["stop_lat"].astype(float)])
    return list(s["stop_id"].astype(str)), lonlat


def _city_mask(lonlat: np.ndarray) -> np.ndarray:
    city = unary_union(load_zones().shapes)
    return shapely.contains_xy(city, lonlat[:, 0], lonlat[:, 1])


def reference_day(at: datetime | None = None) -> date | None:
    """The first Tuesday on or after `at` (default now) that the GTFS covers; None outside the feed."""
    d = (at or config.now()).date()
    d += timedelta(days=(REFERENCE_WEEKDAY - d.weekday()) % 7)
    first, last = gtfs.coverage()
    while d <= last:
        if d >= first and gtfs.service_ids_on(d):
            return d
        d += timedelta(days=7)
    return None


def _pct(n: int | float | None, total: int | float | None) -> float | None:
    if n is None or not total:
        return None
    return round(100.0 * n / total, 1)


def _ind(code: str, ro: str, en: str, value, unit: str, m_ro: str, m_en: str, scope: str) -> Indicator:
    return Indicator(code=code, name=I18n(ro=ro, en=en), value=value, unit=unit,
                     method=I18n(ro=m_ro, en=m_en), scope=scope)


# --- 1. stops in the city ---------------------------------------------------------------------


def stops_in_city() -> tuple[int, int]:
    ids, lonlat = _stops()
    return int(_city_mask(lonlat).sum()), len(ids)


# --- 2. residents near a stop ------------------------------------------------------------------


def residents_near_stops() -> tuple[float, float] | None:
    """(residents in the 40 zones within 400 m of a served stop, residents in the 40 zones); None without GHSL."""
    from app.m1_disruption.impact import pop_grid

    grid = pop_grid()
    if grid is None:
        return None
    served = set(gtfs.departure_index()["stop_id"].astype(str).unique())
    ids, lonlat = _stops()
    keep = [i for i, s in enumerate(ids) if s in served]
    stop_xy = project_lonlats(map(tuple, lonlat[keep]))
    in_city = grid.zone >= 0
    cells, people = grid.xy[in_city], grid.residents[in_city]
    from scipy.spatial import cKDTree  # noqa: PLC0415 - scipy comes with geopandas / r5py

    dist, _ = cKDTree(stop_xy).query(cells, k=1)
    near = dist <= RADIUS_M
    return float(people[near].sum()), float(people.sum())


# --- 3. AC.1 -------------------------------------------------------------------------------------


def ac1(day: date) -> dict:
    """Stops with >= 4 departures of at least one route in the hour from 07:00 and from 16:00."""
    ids, _ = _stops()
    passing: dict[int, set[str]] = {}
    for hour in AC1_HOURS:
        start = local_midnight(day).replace(hour=hour)
        counts = gtfs.count_by_key(start, start + timedelta(hours=1))
        per_route: dict[tuple[str, str], int] = {}
        for (stop, route, _d), n in counts.items():
            per_route[(stop, route)] = per_route.get((stop, route), 0) + n
        passing[hour] = {s for (s, _r), n in per_route.items() if n >= AC1_MIN_DEPARTURES}
    return {"total": len(ids), "h07": len(passing[7]), "h16": len(passing[16]),
            "any": len(passing[7] | passing[16])}


# --- 4. bike km (M5 data) ------------------------------------------------------------------------


def bike_km() -> tuple[float, float] | None:
    """(km of bike ways in the 40 zones, km of those with LTS <= 2); None while M5 data is missing."""
    try:
        from app.m5_bike.osm_bike import bike_data

        d = bike_data()
    except Exception:   # noqa: BLE001 - module not built yet or OSM missing: unknown
        log.info("bike data unavailable; bike km = null", exc_info=True)
        return None
    seen: set[tuple[int, int, int]] = set()
    mids, lens, low = [], [], []
    for i in range(len(d.seg_len)):
        w = int(d.seg_way[i])
        if not d.way_bike[w]:
            continue
        u, v = int(d.seg_u[i]), int(d.seg_v[i])
        k = (min(u, v), max(u, v), w)
        if k in seen:   # a two-way segment listed in both directions counts once
            continue
        seen.add(k)
        c = d.seg_coords[i]
        mids.append(c[len(c) // 2])
        lens.append(float(d.seg_len[i]))
        lts = d.way_lts[w]
        low.append(lts is not None and lts <= 2)
    if not lens:
        return 0.0, 0.0
    inside = _city_mask(np.asarray(mids))
    lens_a, low_a = np.asarray(lens), np.asarray(low)
    return (round(float(lens_a[inside].sum()) / 1000.0, 1),
            round(float(lens_a[inside & low_a].sum()) / 1000.0, 1))


def bike_provenance() -> Provenance | None:
    from app.common import provenance as prov

    p = prov.from_sources("osm")
    if p is None:
        path = config.get_settings().data_dir / "osm" / "timisoara.osm.pbf"
        if not path.is_file():
            return None
        p = prov.for_file("OpenStreetMap (© contributors, ODbL)", path, "https://www.openstreetmap.org")
    return p


# --- 5. P&R (M6 rule) ----------------------------------------------------------------------------


def park_and_ride_count() -> int | None:
    try:
        from app.m6_parking.parking import all_park_and_ride

        return len(all_park_and_ride())
    except Exception:   # noqa: BLE001 - module or data missing: unknown
        log.info("P&R unavailable; count = null", exc_info=True)
        return None


# --- the set -------------------------------------------------------------------------------------


def build_indicators(at: datetime | None = None) -> IndicatorSet:
    at = at or config.now()
    feed = gtfs.feed()
    version = feed.version or "?"
    out: list[Indicator] = []
    provenance: list[Provenance] = [feed.provenance, load_zones().provenance]

    n_city, n_all = stops_in_city()
    out.append(_ind("STOPS_CITY", "Stații în oraș", "Stops in the city", n_city, "stații",
                    f"Stațiile din GTFS SMTT {version} (location_type 0) aflate în poligoanele celor 40 de cartiere.",
                    f"Stops of GTFS SMTT {version} (location_type 0) inside the 40 neighbourhood polygons.",
                    SCOPE_CITY))
    out.append(_ind("STOPS_CITY_SHARE", "Ponderea stațiilor din oraș", "Share of stops in the city",
                    _pct(n_city, n_all), "%",
                    f"Stații în oraș ({n_city}) / toate stațiile din GTFS SMTT {version} ({n_all}) × 100.",
                    f"Stops in the city ({n_city}) / all stops of GTFS SMTT {version} ({n_all}) × 100.",
                    SCOPE_NETWORK))

    res = residents_near_stops()
    if res is not None:
        from app.m1_disruption.impact import pop_provenance

        provenance.append(pop_provenance())
    near, total = (round(res[0]), round(res[1])) if res else (None, None)
    out.append(_ind("RES_400M", "Locuitori la cel mult 400 m de o stație", "Residents within 400 m of a stop",
                    near, "locuitori",
                    f"Suma celulelor GHSL 2020 de 100 m din cele 40 de cartiere al căror centru e la cel mult 400 m "
                    f"(linie dreaptă) de o stație cu cel puțin o plecare în GTFS {version}. {GHSL_LABEL}.",
                    f"Sum of the GHSL 2020 100 m cells in the 40 neighbourhoods whose centre lies within 400 m "
                    f"(straight line) of a stop with at least one departure in GTFS {version}. "
                    "Model GHSL 2020, not a census.",
                    SCOPE_CITY))
    out.append(_ind("RES_400M_SHARE", "Ponderea locuitorilor la cel mult 400 m de o stație",
                    "Share of residents within 400 m of a stop", _pct(near, total), "%",
                    f"Locuitori la cel mult 400 m de o stație / toți locuitorii celor 40 de cartiere"
                    f"{f' ({total})' if total else ''} × 100. {GHSL_LABEL}.",
                    "Residents within 400 m of a stop / all residents of the 40 neighbourhoods × 100. "
                    "Model GHSL 2020, not a census.",
                    SCOPE_CITY))

    day = reference_day(at)
    a = ac1(day) if day else None
    day_txt = day.isoformat() if day else "—"
    for code, key, ro_h, en_h in (("AC1_0700", "h07", "07:00–08:00", "07:00–08:00"),
                                  ("AC1_1600", "h16", "16:00–17:00", "16:00–17:00"),
                                  ("AC1_ANY", "any", "07:00–08:00 sau 16:00–17:00", "07:00–08:00 or 16:00–17:00")):
        n = a[key] if a else None
        out.append(_ind(code, f"AC.1: stații cu ≥ 4 plecări pe oră ale unei linii ({ro_h})",
                        f"AC.1: stops with ≥ 4 departures per hour of one route ({en_h})",
                        _pct(n, a["total"]) if a else None, "%",
                        f"Stații la care o linie (ambele sensuri adunate) are cel puțin 4 plecări programate între "
                        f"{ro_h}, marți {day_txt}, GTFS {version}: {n} din {a['total'] if a else '—'} stații. "
                        "Stil AC.1 (TEN-T 2024/1679), nu metoda oficială.",
                        f"Stops where one route (both directions together) has at least 4 scheduled departures "
                        f"between {en_h} on Tuesday {day_txt}, GTFS {version}: {n} of {a['total'] if a else '—'} "
                        "stops. AC.1-style (TEN-T 2024/1679), not the official method.",
                        SCOPE_NETWORK))

    bk = bike_km()
    bp = bike_provenance() if bk is not None else None
    if bp is not None:
        provenance.append(bp)
    out.append(_ind("BIKE_KM", "Km de piste și benzi de biciclete", "Km of bike ways",
                    bk[0] if bk else None, "km",
                    "Lungimea segmentelor OSM marcate ca infrastructură pentru biciclete (pistă, bandă, drum "
                    "dedicat; regula M5) al căror mijloc e în cele 40 de cartiere. Lipsa din OSM = necunoscut.",
                    "Length of the OSM segments tagged as bike infrastructure (track, lane, designated way; M5 "
                    "rule) whose midpoint lies in the 40 neighbourhoods. Missing in OSM = unknown.",
                    SCOPE_CITY))
    out.append(_ind("BIKE_KM_LTS2", "Km de piste cu stres redus (LTS ≤ 2)", "Km of low-stress bike ways (LTS ≤ 2)",
                    bk[1] if bk else None, "km",
                    "Din km de piste și benzi: cei cu nivel de stres în trafic (LTS) 1 sau 2, după tabelul M5 "
                    "(viteză maximă OSM, implicit 50 km/h în oraș).",
                    "Of the km of bike ways: those with Level of Traffic Stress 1 or 2, by the M5 table "
                    "(OSM maxspeed, urban default 50 km/h).",
                    SCOPE_CITY))

    pr = park_and_ride_count()
    out.append(_ind("PR_OPTIONS", "Opțiuni Park & Ride", "Park & Ride options", pr, "opțiuni",
                    "Capete de linie la peste 3 km de Piața Victoriei cu o parcare Timpark la cel mult 500 m "
                    "(linie dreaptă). Fără date de ocupare.",
                    "Line ends more than 3 km from Piața Victoriei with a Timpark lot within 500 m (straight line). "
                    "No occupancy data.",
                    SCOPE_CITY))
    if pr is not None:
        provenance.append(load_zones().provenance.model_copy(update={
            "source": "Primăria Timișoara, Timpark (/api/mobile/parking)",
            "url": "https://cont.primariatm.ro/api/mobile/parking", "note": "fără date de ocupare / no occupancy data"}))
    return IndicatorSet(generatedAt=iso(config.real_now()), indicators=out, provenance=provenance)


def indicators_key(at: datetime | None = None) -> str:
    """Job-cache key: GTFS hash, reference day, data files the indicators read, and the rule version."""
    s = config.get_settings()
    files = []
    for rel in ("osm/timisoara.osm.pbf", "pop/ghsl_2020_100m.tif", "city-api-2026-11-13/parking.json",
                "city-api-2026-11-13/zones.geojson"):
        p = s.data_dir / rel
        files.append((rel, p.stat().st_mtime if p.is_file() else None))
    app_dir = Path(__file__).resolve().parents[1]
    for rel in ("m5_bike/osm_bike.py", "m5_bike/lts.py", "m6_parking/parking.py"):   # M5/M6 rules may change
        p = app_dir / rel
        files.append((rel, p.stat().st_mtime if p.is_file() else None))
    day = reference_day(at)
    blob = json.dumps([INDICATORS_VERSION, gtfs.feed().sha256, str(day), files], sort_keys=True)
    return "m7:indicators:" + hashlib.sha256(blob.encode()).hexdigest()[:16]


def notice_lead() -> tuple[list[Indicator], Provenance | None]:
    """R15: median lead time from STPT notice to works start, over the notices in /api/history.

    Computed on every call (not job-cached): a new publish changes it. One value per STPT notice
    (the platform row replaces the back-filled one, as in /api/history)."""
    from statistics import median

    from app.common import provenance as prov
    from app.m7_compliance.history import history

    leads = {}
    for r in history():
        if r.leadHours is not None:
            leads.setdefault(r.sourceUrl or r.closureId, r.leadHours)
    n = len(leads)
    value = round(median(leads.values()), 1) if n else None
    late = sum(1 for v in leads.values() if v < 24)
    out = [
        _ind("NOTICE_LEAD_MEDIAN", "Preaviz median al anunțurilor STPT", "Median lead time of STPT notices",
             value, "h",
             f"Mediana orelor dintre publicarea anunțului STPT pe stpt.ro și începutul lucrării, pe cele {n} anunțuri "
             f"din istoric (/api/history) cu fereastra citită din text; {late} {'a venit' if late == 1 else 'au venit'} "
             "cu mai puțin de 24 h înainte.",
             f"Median of the hours between the STPT notice going up on stpt.ro and the works start, over the {n} "
             f"notices in the history (/api/history) whose window is read from the text; {late} came less than "
             "24 h ahead.",
             SCOPE_NETWORK),
        _ind("NOTICE_LEAD_N", "Anunțuri STPT cu preaviz măsurat", "STPT notices with a measured lead time",
             n, "anunțuri",
             "Câte anunțuri intră în mediana de mai sus.", "How many notices the median above counts.",
             SCOPE_NETWORK),
    ]
    p = prov.provenance("STPT, anunțuri / notices (stpt.ro), înregistrarea noastră", config.real_now(),
                        prov.STPT_POSTS_URL, None, f"{n} anunțuri / notices") if n else None
    return out, p


def indicators(at: datetime | None = None) -> IndicatorSet:
    from app.common.jobs import compute_and_cache

    base = compute_and_cache(indicators_key(at), lambda: build_indicators(at))
    try:
        lead, p = notice_lead()
    except Exception:   # noqa: BLE001 - the other indicators never fail with this one
        log.exception("notice lead time indicator failed")
        return base
    return base.model_copy(update={"indicators": list(base.indicators) + lead,
                                   "provenance": list(base.provenance) + ([p] if p else [])})
