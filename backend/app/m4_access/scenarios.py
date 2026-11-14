"""Scenarios and mitigations (SPEC §6.4 "Scenarios and mitigations", D-009).

A scenario is the closure plus a list of mitigations; it is stored in
$DATA_DIR/state/scenarios/<id>.json and never changes the closure itself. Its
impact re-runs m1-core on a modified copy of the closure in memory:

- `window`: the works move to another time: re-match (the timetable in force
  may change) and recount the Impact on the new window.
- `segment`: another section is closed instead: the geometry is replaced, the
  notice's route actions are dropped, the stops are matched on the new geometry.
- `frequency`: a line runs every N minutes in the window. Departures lost stay a
  count on the planned timetable, so they do not change; the added departures are
  reported in a note (simulare) and passed to the access model when it supports them.
- `bike_lane`: changes only the bike numbers (M5).
- `park_and_ride`: changes no transit number; it adds an item and the note
  „nu modifică cifrele de acces”.

Stored decisions of the closure (ticks) apply to the re-matched rows with the
same (stop, route, direction); unsure rows without a decision do not count.

access (M4 access agent) and detourLoad / bike (detour-bike agent) come from
their modules through lazy imports; when a module is missing they are null with
a note, never invented.

Ids: prepared scenarios start with `sp_`, the automatic „Nicio măsură” is
`s0_<closureId>`, the others `sc_<time>_<random>`.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import logging
import math
from shapely.geometry import shape

from app.common import state
from app.common.city import load_network, load_parking
from app.common.errors import invalid, not_found
from app.common.geo import haversine_m
from app.common.provenance import provenance
from app.common.timeutil import iso, parse_iso
from app.config import now
from app.m1_disruption import impact as imp
from app.m1_disruption import matching
from app.m4_access.windows import load_closure, lost_keys, num_en, num_ro, span_en, span_ro
from app.models.base import I18n
from app.models.v2 import (
    Scenario,
    ScenarioCompare,
    ScenarioImpact,
    ScenarioInput,
    ScenarioNote,
    ScenarioSummary,
)

log = logging.getLogger("reteaua_vie.scenarios")

KIND = "scenarios"
PREPARED_PREFIX = "sp_"
NOTHING_PREFIX = "s0_"
NOTHING_TITLE = I18n(ro="Nicio măsură", en="Do nothing")
MAX_HEADWAY = 120.0
DEFAULT_DEST, DEFAULT_MINUTES = "hospital", 30
SIM_LABEL = "simulare"


# --- storage ----------------------------------------------------------------------------


def nothing_id(closure_id: str) -> str:
    return (NOTHING_PREFIX + closure_id)[:120]


def is_prepared(scenario_id: str) -> bool:
    return scenario_id.startswith(PREPARED_PREFIX)


def get(scenario_id: str) -> Scenario:
    try:
        data = state.read(KIND, scenario_id)
    except ValueError:
        data = None
    if data is None:
        raise not_found(f"No scenario {scenario_id}.")
    return Scenario.model_validate(data)


def _check_mitigations(inp: ScenarioInput, closure: dict) -> None:
    n = load_network()
    lots = {f["properties"]["id"] for f in load_parking().features if f["properties"]["kind"] == "lot"}
    for m in inp.mitigations:
        if m.kind == "frequency":
            if m.routeId not in n.route_by_id:
                raise invalid(f"Unknown route {m.routeId}.")
            if not 1 <= m.headwayMinutes <= MAX_HEADWAY:
                raise invalid("headwayMinutes must be 1 to 120.")
        elif m.kind == "transit_through":
            for rid in m.routeIds:
                if rid not in n.route_by_id:
                    raise invalid(f"Unknown route {rid}.")
        elif m.kind == "window":
            if parse_iso(m.end) <= parse_iso(m.start):
                raise invalid("The window must end after it starts.")
        elif m.kind == "park_and_ride":
            if m.stopId not in n.stop_by_id:
                raise invalid(f"Unknown stop {m.stopId}.")
            if m.lotId is not None and m.lotId not in lots:
                raise invalid(f"Unknown Timpark lot {m.lotId}.")
    if sum(1 for m in inp.mitigations if m.kind == "window") > 1:
        raise invalid("At most one window mitigation per scenario.")
    if sum(1 for m in inp.mitigations if m.kind == "transit_through") > 1:
        raise invalid("At most one transit_through mitigation per scenario.")
    if sum(1 for m in inp.mitigations if m.kind == "segment") > 1:
        raise invalid("At most one segment mitigation per scenario.")


def save(inp: ScenarioInput, scenario_id: str | None = None) -> Scenario:
    """Validate and store a scenario (a new id unless one is given)."""
    closure, _ = load_closure(inp.closureId)
    _check_mitigations(inp, closure)
    sid = scenario_id or state.new_id("sc")
    old = state.read(KIND, sid) if state.exists(KIND, sid) else None
    created = (old or {}).get("createdAt") or iso(now())
    sc = Scenario(id=sid, createdAt=created, **inp.model_dump(mode="json", by_alias=True))
    state.write(KIND, sid, sc)
    return sc


def create(inp: ScenarioInput) -> Scenario:
    """POST /api/scenarios: also makes sure the closure has its „Nicio măsură” scenario."""
    ensure_nothing(inp.closureId)
    return save(inp)


def ensure_nothing(closure_id: str) -> Scenario:
    """The automatic „Nicio măsură” scenario of a closure (the closure as drawn)."""
    sid = nothing_id(closure_id)
    if state.exists(KIND, sid):
        return get(sid)
    return save(ScenarioInput(closureId=closure_id, title=NOTHING_TITLE, mitigations=[]), sid)


def list_for(closure_id: str) -> list[Scenario]:
    """Scenarios of a closure: the prepared ones first, then „Nicio măsură”, then the others by time."""
    load_closure(closure_id)
    ensure_nothing(closure_id)
    out = [Scenario.model_validate(s) for s in state.list_all(KIND) if s.get("closureId") == closure_id]

    def order(s: Scenario) -> tuple:
        group = 0 if is_prepared(s.id) else 1 if s.id.startswith(NOTHING_PREFIX) else 2
        return (group, s.id if group == 0 else s.createdAt, s.id)

    return sorted(out, key=order)


def fingerprint(scenario: Scenario) -> str:
    """What a scenario's impact depends on: the scenario and its closure (input + decisions)."""
    from app.common.jobs import closure_fingerprint

    blob = json.dumps([scenario.model_dump(mode="json", exclude={"createdAt", "title"}),
                       closure_fingerprint(scenario.closureId)], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# --- lazy links to the other M4/M5 modules ------------------------------------------------------


def _optional(module: str, *attrs: str):
    """The first existing function among `attrs` of a module, or None while it does not exist."""
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as e:
        if e.name and module.startswith(e.name):
            return None
        raise
    for a in attrs:
        fn = getattr(mod, a, None)
        if callable(fn):
            return fn
    return None


def _access(closure: dict, lost: set, frequencies: list[dict]) -> tuple[object | None, str | None]:
    """AccessImpact from the access agent's module, or (None, reason)."""
    fn = _optional("app.m4_access.access", "access_for")
    if fn is None:
        return None, "acces: modulul M4 de accesibilitate nu e gata (necunoscut) / access module not ready (unknown)"
    try:
        if frequencies:
            try:
                return fn(closure, lost, dest=DEFAULT_DEST, minutes=DEFAULT_MINUTES, frequencies=frequencies), None
            except TypeError:
                res = fn(closure, lost, dest=DEFAULT_DEST, minutes=DEFAULT_MINUTES)
                return res, ("frecvența nu e încă modelată în accesibilitate / frequency not yet in the access model")
        return fn(closure, lost, dest=DEFAULT_DEST, minutes=DEFAULT_MINUTES), None
    except Exception as e:  # access is an estimate on the side: never fail the scenario for it
        log.exception("access for scenario failed")
        return None, f"acces indisponibil ({type(e).__name__}) / access unavailable"


def _detour(closure: dict, same_geometry: bool):
    """DetourLoad from the detour agent's module: the stored closure's cached one when the
    geometry is unchanged, else computed on the modified copy (segment)."""
    try:
        result = None
        if same_geometry:
            fn = _optional("app.m4_access.detour", "compute_for")
            result = fn(closure["id"]) if fn is not None else None
        if result is None:
            fn = _optional("app.m4_access.detour", "compute_detour_load")
            result = fn(closure) if fn is not None else None
        spill = _optional("app.m4_access.spillover", "with_spillover")
        return spill(closure, result) if result is not None and spill is not None else result
    except Exception:
        log.exception("detour load for scenario failed")
        return None


def _bike(closure: dict, lanes: list[dict]) -> tuple[object | None, str | None]:
    for module in ("app.m5_bike.bike", "app.m5_bike"):
        fn = _optional(module, "bike_impact_for")
        if fn is not None:
            break
    else:
        return None, ("Cifrele pentru biciclete: modulul M5 nu e gata (necunoscut) / "
                      "bike figures: the M5 module is not ready (unknown)")
    try:
        try:
            return fn(closure, extra_lanes=lanes), None
        except TypeError:
            return fn(closure), "pista temporară nu e încă modelată în M5 / the temporary lane is not modelled yet"
    except Exception as e:
        log.exception("bike impact for scenario failed")
        return None, f"biciclete indisponibil ({type(e).__name__}) / bike figures unavailable"


# --- the modified closure ---------------------------------------------------------------------


def apply_mitigations(closure: dict, rows: list[dict], mitigations: list) -> tuple[dict, list[dict], list[ScenarioNote]]:
    """(closure copy, rows, notes) after the window and segment mitigations."""
    c = copy.deepcopy(closure)
    notes: list[ScenarioNote] = []
    rematch = False
    for m in mitigations:
        if m.kind == "window":
            old = (parse_iso(c["window"]["start"]), parse_iso(c["window"]["end"]))
            c["window"] = {"start": m.start, "end": m.end}
            new = (parse_iso(m.start), parse_iso(m.end))
            notes.append(ScenarioNote(kind="window", text=I18n(
                ro=f"Lucrarea mutată: {span_ro(*new)} (în loc de {span_ro(*old)}). Stațiile și plecările sunt "
                   f"recalculate pe orarul acelei ferestre.",
                en=f"Works moved to {span_en(*new)} (instead of {span_en(*old)}). Stops and departures are "
                   f"recomputed on that window's timetable.")))
            rematch = True
        elif m.kind == "segment":
            c.update(geometry=m.geometry.model_dump(mode="json"), routeActions=None, temporaryRoutes=None,
                     kind="drawn", sourceText=None)
            notes.append(ScenarioNote(kind="segment", text=I18n(
                ro="Se închide alt tronson: stațiile sunt potrivite pe noua geometrie (zona de "
                   f"{num_ro(c.get('bufferMeters') or 30)} m), fără acțiunile din anunț.",
                en="Another section is closed: stops are matched on the new geometry "
                   f"({num_en(c.get('bufferMeters') or 30)} m buffer), without the notice's actions.")))
            rematch = True
    if not rematch:
        return _transit(c, rows, notes, mitigations)
    decided = {imp.row_key(r): r["confirmed"] for r in rows if r.get("confirmed") is not None}
    new_rows, _ = matching.match_closure(c)
    for r in new_rows:
        r["confirmed"] = decided.get(imp.row_key(r))
    open_rows = sum(1 for r in new_rows if r["state"] == "unsure" and r.get("confirmed") is None)
    if open_rows:
        notes.append(ScenarioNote(kind="segment" if c.get("kind") == "drawn" and not c.get("routeActions") else "window",
                                  text=I18n(ro=f"{open_rows} rânduri neclare nu sunt numărate până la o decizie.",
                                            en=f"{open_rows} unsure rows are not counted until a person decides."),
                                  value=float(open_rows), unit="rânduri"))
    return _transit(c, new_rows, notes, mitigations)


def _transit(c: dict, rows: list[dict], notes: list[ScenarioNote], mitigations: list) -> tuple[dict, list[dict], list[ScenarioNote]]:
    """R10: the `transit_through` mitigations, after the window and segment ones."""
    from app.m4_access import transit_through as tt

    for m in mitigations:
        if m.kind == "transit_through":
            c, rows, note = tt.apply(c, rows, m)
            notes.append(note)
    return c, rows, notes


def frequency_note(closure: dict, m) -> tuple[ScenarioNote, dict]:
    """Departures the line would add in the window at the new headway (simulare).

    Existing = the departures of the line at its busiest stop per direction in the window
    (= the trips that run through); target = window minutes / headway per direction.
    """
    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    tt = imp.timetable_for(start)
    cw = imp.count_window(start, end, tt)
    counts = imp.departure_counts(cw, tt) or {}
    name = matching.route_short_name(m.routeId)
    dirs = matching.directions_of(m.routeId, tt) or [0]
    minutes = (end - start).total_seconds() / 60
    existing = {d: max([n for (s, r, dd), n in counts.items() if r == m.routeId and dd == d] or [0]) for d in dirs}
    target = math.floor(minutes / m.headwayMinutes)
    added = sum(max(0, target - existing[d]) for d in dirs)
    exist_ro = ", ".join(num_ro(existing[d]) for d in dirs)
    note = ScenarioNote(kind="frequency", value=float(added), unit="plecări", text=I18n(
        ro=f"Linia {name} la {num_ro(m.headwayMinutes)} minute: +{num_ro(added)} plecări în fereastră "
           f"({SIM_LABEL}: curse adăugate în orar; acum {exist_ro} pe sens). Plecările pierdute nu se schimbă: "
           f"sunt numărate pe orarul planificat.",
        en=f"Line {name} every {num_en(m.headwayMinutes)} minutes: +{num_en(added)} departures in the window "
           f"(simulation: trips added to the timetable; now {exist_ro} per direction). Departures lost do not "
           f"change: they are counted on the planned timetable."))
    return note, {"routeId": m.routeId, "headwayMinutes": float(m.headwayMinutes)}


def park_and_ride_note(m) -> ScenarioNote:
    n = load_network()
    stop = n.stop_by_id[m.stopId]
    lot_txt_ro = lot_txt_en = ""
    walk = None
    if m.lotId:
        lot = next(f for f in load_parking().features if f["properties"]["id"] == m.lotId)
        c = shape(lot["geometry"]).centroid
        walk = round(haversine_m(stop["location"][0], stop["location"][1], c.x, c.y))
        lot_txt_ro = f", parcarea {lot['properties']['name'] or m.lotId} (~{num_ro(walk)} m, linie dreaptă)"
        lot_txt_en = f", lot {lot['properties']['name'] or m.lotId} (~{num_en(walk)} m, straight line)"
    lines = ", ".join(matching.route_short_name(r) for r in stop.get("routeIds") or [])
    return ScenarioNote(kind="park_and_ride", value=float(walk) if walk is not None else None,
                        unit="m" if walk is not None else None, text=I18n(
        ro=f"Park & Ride la stația {stop['name']} (liniile {lines}){lot_txt_ro}: nu modifică cifrele de acces. "
           f"Fără date de ocupare.",
        en=f"Park & Ride at stop {stop['name']} (lines {lines}){lot_txt_en}: does not change the access figures. "
           f"No occupancy data."))


# --- the impact ---------------------------------------------------------------------------


def compute_impact(scenario_id: str) -> ScenarioImpact:
    sc = get(scenario_id)
    closure, analysis = load_closure(sc.closureId)
    c, rows, notes = apply_mitigations(closure, analysis["stops"], sc.mitigations)
    impact = imp.build_impact(c, rows)
    lost = set(lost_keys(rows))

    frequencies, lanes = [], []
    for m in sc.mitigations:
        if m.kind == "frequency":
            note, f = frequency_note(c, m)
            notes.append(note)
            frequencies.append(f)
        elif m.kind == "park_and_ride":
            notes.append(park_and_ride_note(m))
        elif m.kind == "bike_lane":
            lanes.append(m.geometry.model_dump(mode="json"))
    if not sc.mitigations:
        notes.append(ScenarioNote(kind="none", text=I18n(ro="Nicio măsură: lucrarea așa cum e în dosar.",
                                                         en="Do nothing: the closure as it stands.")))

    access, why = _access(c, lost, frequencies)
    if why:
        notes.append(ScenarioNote(kind="frequency" if frequencies and access is not None else "none",
                                  text=I18n(ro=why.split(" / ")[0], en=why.split(" / ")[-1])))
    elif frequencies and access is not None:
        unmodelled = any("nu e modelat" in (p.note or "") for p in access.provenance)
        notes.append(ScenarioNote(kind="frequency", text=I18n(
            ro="Frecvența nu e încă modelată în accesibilitate." if unmodelled else
            "Frecvența intră în calculul accesibilității (estimare).",
            en="Frequency is not modelled in the access figures yet." if unmodelled else
            "Frequency is part of the access estimate.")))
    bike = None
    if lanes:
        bike, why = _bike(c, lanes)
        lane_m = sum(_length_m(g) for g in lanes)
        notes.append(ScenarioNote(kind="bike_lane", value=float(round(lane_m)), unit="m", text=I18n(
            ro=f"Pistă temporară pentru biciclete, {num_ro(lane_m)} m: schimbă doar cifrele pentru biciclete.",
            en=f"Temporary bike lane, {num_en(lane_m)} m: changes only the bike figures.")))
        if why:
            notes.append(ScenarioNote(kind="bike_lane", text=I18n(ro=why.split(" / ")[0], en=why.split(" / ")[-1])))
    detour = _detour(c, same_geometry=c.get("geometry") == closure.get("geometry"))

    prov = list(impact.provenance)
    prov.append(provenance("Rețeaua Vie, scenariu / scenario", now(), None, None,
                           f"{SIM_LABEL}: măsurile se aplică unei copii a lucrării, nu lucrării din dosar"))
    for extra in (access, detour, bike):
        for p in getattr(extra, "provenance", None) or []:
            if p not in prov:
                prov.append(p)
    return ScenarioImpact(
        scenarioId=sc.id, closureId=sc.closureId, impact=impact, access=access, detourLoad=detour,
        summary=ScenarioSummary(
            residentsLosingStop=impact.totals.residentsLosingStop,
            residentsLosingAccess=access.totals.residentsLosing if access is not None else None,
            departuresLost=impact.totals.departuresLost),
        provenance=prov, notes=notes, bike=bike)


def _length_m(geojson: dict) -> float:
    from app.common.geo import length_m

    return float(length_m(shape(geojson)))


def compare(a: str, b: str) -> ScenarioCompare:
    return ScenarioCompare(a=compute_impact(a), b=compute_impact(b))


# --- job keys (the routes and warm_decide use the same ones) ----------------------------------------


def modules_stamp() -> str:
    """Which optional modules exist: a cached impact made without one is redone once it lands."""
    found = [_optional("app.m4_access.access", "access_for"), _optional("app.m5_bike.bike", "bike_impact_for"),
             _optional("app.m4_access.detour", "compute_detour_load")]
    return "".join("1" if f is not None else "0" for f in found)


# v2: results cached before the access model took the frequency (bd18b9f) said it was not modelled
def impact_job_key(scenario_id: str) -> str:
    return f"scenario-impact:v2:{modules_stamp()}:{scenario_id}:{fingerprint(get(scenario_id))}"


def compare_job_key(a: str, b: str) -> str:
    return f"scenario-compare:v2:{modules_stamp()}:{a}:{fingerprint(get(a))}:{b}:{fingerprint(get(b))}"
