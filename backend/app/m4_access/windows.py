"""Time windows and phasing for a closure (SPEC §6.4 "Windows", D-009).

The platform suggests the better time itself: for a works of `hours` hours,
every start on a 30-minute grid in [from, to] is a candidate, and its cost is
the scheduled departures lost at the closure's lost (stop, route, direction)
rows inside that window. Tie-break: fewer conflicting closures, then fewer
residents losing their stop. Overlapping candidates are removed; the top 10
remain.

Phasing (`phases=N`): the closure geometry is cut into N consecutive sections
of equal length; each section is re-matched with m1-core's matching on a
temporary closure (never stored) and gets its own best window, with no two
phases overlapping in time.

Departures are counted on the timetable in force before the works
(m1-core's `timetable_for`), the same one the Impact uses.

Public: suggest(closure_id, hours=, start=, end=, phases=) -> WindowSuggestion
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import groupby

import numpy as np
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge, substring

from app.common import gtfs, state
from app.common.errors import invalid, not_found
from app.common.geo import from_geojson, to_geojson, to_metric, to_wgs84
from app.common.timeutil import iso, local_midnight, parse_iso
from app.config import TZ, now
from app.m1_disruption import impact as imp
from app.m1_disruption import matching
from app.m1_disruption.conflicts import find_conflicts
from app.models.base import I18n, Provenance, Window
from app.models.v2 import WindowCandidate, WindowPhase, WindowSuggestion

GRID_MIN = 30
DEFAULT_DAYS = 14
MAX_DAYS = 90
TOP_N = 10
MAX_PHASES = 4
RESIDENT_TIE_CAP = 60          # residents are computed for at most this many tied candidates per group
DEFAULT_HOURS = 8.0            # when the closure is longer than the search range

Key = tuple[str, str, int]

WEEKDAYS_RO = ("luni", "marți", "miercuri", "joi", "vineri", "sâmbătă", "duminică")
WEEKDAYS_EN = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS_RO = ("ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sep", "oct", "nov", "dec")
MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# --- words for people ----------------------------------------------------------------


def num_ro(n: int | float | None) -> str:
    """1766 -> '1.766' (Romanian thousands separator)."""
    if n is None:
        return "necunoscut"
    return f"{int(round(n)):,}".replace(",", ".")


def num_en(n: int | float | None) -> str:
    return "unknown" if n is None else f"{int(round(n)):,}"


def _hm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def span_ro(start: datetime, end: datetime) -> str:
    """'sâmbătă 14 nov, 22:30 – duminică 15 nov, 06:30' or 'duminică 8 nov, 10:00–18:00'."""
    s, e = start.astimezone(TZ), end.astimezone(TZ)
    day = f"{WEEKDAYS_RO[s.weekday()]} {s.day} {MONTHS_RO[s.month - 1]}"
    if s.date() == e.date():
        return f"{day}, {_hm(s)}–{_hm(e)}"
    return f"{day}, {_hm(s)} – {WEEKDAYS_RO[e.weekday()]} {e.day} {MONTHS_RO[e.month - 1]}, {_hm(e)}"


def span_en(start: datetime, end: datetime) -> str:
    s, e = start.astimezone(TZ), end.astimezone(TZ)
    day = f"{WEEKDAYS_EN[s.weekday()]} {s.day} {MONTHS_EN[s.month - 1]}"
    if s.date() == e.date():
        return f"{day}, {_hm(s)}–{_hm(e)}"
    return f"{day}, {_hm(s)} – {WEEKDAYS_EN[e.weekday()]} {e.day} {MONTHS_EN[e.month - 1]}, {_hm(e)}"


# --- inputs ----------------------------------------------------------------------------


def load_closure(closure_id: str) -> tuple[dict, dict]:
    """(closure, analysis) from the state store; 404 when missing or never analyzed."""
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id}.")
    analysis = state.read("closures", closure_id, state.PART_ANALYSIS)
    if analysis is None:
        raise not_found(f"Closure {closure_id} was never analyzed.", code="NOT_ANALYZED")
    return closure, analysis


def lost_keys(rows: list[dict]) -> list[Key]:
    """(stop, route, direction) rows that count as lost (m1-core's rule: confirmed or affected)."""
    return sorted({imp.row_key(r) for r in rows if imp.counts_as_lost(r)})


def closure_hours(closure: dict) -> float:
    w = closure["window"]
    return (parse_iso(w["end"]) - parse_iso(w["start"])).total_seconds() / 3600


def _ceil_grid(dt: datetime) -> datetime:
    dt = dt.astimezone(TZ).replace(second=0, microsecond=0)
    extra = (-dt.minute) % GRID_MIN
    return dt + timedelta(minutes=extra)


@dataclass
class SearchRange:
    start: datetime            # first candidate start (on the grid)
    end: datetime              # last allowed window end
    hours: float
    notes: list[tuple[str, str]]   # (ro, en)


def search_range(closure: dict, tt: imp.Timetable, hours: float | None,
                 start: str | None, end: str | None) -> SearchRange:
    notes: list[tuple[str, str]] = []
    s = _ceil_grid(parse_iso(start) if start else now())
    e = parse_iso(end) if end else s + timedelta(days=DEFAULT_DAYS)
    if e <= s:
        raise invalid("`to` must be after `from`.")
    if e - s > timedelta(days=MAX_DAYS):
        e = s + timedelta(days=MAX_DAYS)
        notes.append((f"Intervalul de căutare a fost limitat la {MAX_DAYS} de zile.",
                      f"The search range was limited to {MAX_DAYS} days."))
    first, last = tt.coverage()
    feed_lo, feed_hi = local_midnight(first), local_midnight(last + timedelta(days=1))
    if s < feed_lo:
        s = _ceil_grid(feed_lo)
    if hours is None:
        hours = closure_hours(closure)
        if hours <= 0 or s + timedelta(hours=hours) > max(e, s):
            notes.append((f"Lucrarea din anunț durează {num_ro(hours)} ore, mai mult decât intervalul de căutare: "
                           f"căutăm ferestre de {num_ro(DEFAULT_HOURS)} ore.",
                           f"The closure lasts {num_en(hours)} h, longer than the search range: "
                           f"searching {num_en(DEFAULT_HOURS)}-hour windows."))
            hours = DEFAULT_HOURS
    if not (0.5 <= hours <= 24 * MAX_DAYS):
        raise invalid("`hours` must be between 0.5 and 2160.")
    # the last window must end before the timetable ends (and before `to` + hours)
    limit = min(e + timedelta(hours=hours), feed_hi)
    if feed_hi < e + timedelta(hours=hours):
        notes.append((f"Orarul GTFS ({tt.version or 'curent'}) se termină pe {last.day} "
                      f"{MONTHS_RO[last.month - 1]} {last.year}: căutăm doar până atunci.",
                      f"The GTFS timetable ({tt.version or 'current'}) ends on {last.isoformat()}: "
                      f"the search stops there."))
    if s + timedelta(hours=hours) > limit:
        raise invalid("No window of that length fits in the search range and the timetable "
                      f"({first} – {last}).", code="OUTSIDE_FEED")
    return SearchRange(s, limit, float(hours), notes)


# --- departures per minute on the right timetable -----------------------------------------


def minute_costs(tt: imp.Timetable, keys: list[Key], start: datetime, end: datetime) -> np.ndarray:
    """Departures of `keys` per minute in [start, end), on the timetable in force before the works.

    The current feed uses foundation's departure index; an older feed from
    gtfs-history (Mocioni: 4.29) is counted per 30-minute slot with m1-core's
    counter and spread evenly over the slot's minutes (the grid is 30 min, so a
    window that starts on the grid and lasts a multiple of 30 min is exact).
    """
    n = int(math.ceil((end - start).total_seconds() / 60))
    if not keys:
        return np.zeros(n, dtype=np.float64)
    if not tt.history:
        return gtfs.minute_counts(start, end, keys=keys).astype(np.float64)
    keyset = set(keys)
    out = np.zeros(n, dtype=np.float64)
    for i in range(0, n, GRID_MIN):
        a = start + timedelta(minutes=i)
        b = min(end, a + timedelta(minutes=GRID_MIN))
        c = tt.counts(a, b)
        total = sum(v for k, v in c.items() if k in keyset)
        width = min(GRID_MIN, n - i)
        out[i:i + width] = total / width
    return out


@dataclass
class Candidate:
    start: datetime
    end: datetime
    departures: int
    conflicts: int
    residents: int | None = None
    residents_done: bool = False

    def overlaps(self, other: "Candidate") -> bool:
        return self.start < other.end and other.start < self.end


def residents_in(tt: imp.Timetable, keys: list[Key], start: datetime, end: datetime) -> int | None:
    """Residents losing their stop if the works ran in [start, end) (m1-core's GHSL method)."""
    counts = tt.counts(start, end)
    svc = imp.ServiceState.build(counts, set(keys))
    res = imp.residents_losing(svc.suspended_stops(), svc)
    if res is None:
        return None
    return int(round(sum(v[0] for v in res.values())))


# --- conflicts -------------------------------------------------------------------------------


def conflict_windows(closure: dict, rng: SearchRange) -> list[tuple[str, datetime, datetime]]:
    """Other stored closures that conflict with this one (same stops or corridor) anywhere in the range.

    Returns (otherClosureId, start, end) of each such closure's own window.
    """
    probe = dict(closure, window={"start": iso(rng.start), "end": iso(rng.end)})
    others = {c["id"]: c for c in state.list_all("closures")}
    out = []
    seen = set()
    for c in find_conflicts(probe, list(others.values())):
        if c.otherClosureId in seen or c.otherClosureId not in others:
            continue
        seen.add(c.otherClosureId)
        w = others[c.otherClosureId]["window"]
        out.append((c.otherClosureId, parse_iso(w["start"]), parse_iso(w["end"])))
    return out


def _count_conflicts(cw: list[tuple[str, datetime, datetime]], s: datetime, e: datetime) -> int:
    return sum(1 for _, a, b in cw if a < e and s < b)


# --- ranking ----------------------------------------------------------------------------------


def candidates(costs: np.ndarray, rng: SearchRange, cw: list[tuple[str, datetime, datetime]]) -> list[Candidate]:
    cs = np.concatenate([[0.0], np.cumsum(costs)])
    h = int(round(rng.hours * 60))
    out = []
    i = 0
    while i + h <= len(costs):
        s = rng.start + timedelta(minutes=i)
        e = s + timedelta(minutes=h)
        out.append(Candidate(s, e, int(round(cs[i + h] - cs[i])), _count_conflicts(cw, s, e)))
        i += GRID_MIN
    return out


def rank(cands: list[Candidate], tt: imp.Timetable, keys: list[Key], top: int = TOP_N,
         taken: list[Candidate] | None = None) -> list[Candidate]:
    """Least departures lost, then fewer conflicts, then fewer residents losing their stop, then earlier.

    Overlapping candidates are removed (greedy in rank order). `taken` = windows already
    used (phasing): candidates overlapping them are skipped too.
    """
    blocked = list(taken or [])
    chosen: list[Candidate] = []
    ordered = sorted(cands, key=lambda c: (c.departures, c.conflicts, c.start))
    for _, grp in groupby(ordered, key=lambda c: (c.departures, c.conflicts)):
        if len(chosen) >= top:
            break
        members = [c for c in grp if not any(c.overlaps(o) for o in blocked + chosen)]
        if len(members) > 1:
            for c in members[:RESIDENT_TIE_CAP]:
                c.residents = residents_in(tt, keys, c.start, c.end)
                c.residents_done = True
            members.sort(key=lambda c: (c.residents is None or not c.residents_done,
                                        c.residents if c.residents is not None else 0, c.start))
        for c in members:
            if len(chosen) >= top:
                break
            if not any(c.overlaps(o) for o in blocked + chosen):
                chosen.append(c)
    for c in chosen:
        if not c.residents_done:
            c.residents = residents_in(tt, keys, c.start, c.end)
            c.residents_done = True
    return chosen


# --- phasing -----------------------------------------------------------------------------------


def _one_line(geom) -> LineString | None:
    """A single metric LineString: merged parts, or the parts chained in order."""
    if isinstance(geom, LineString):
        return geom
    if isinstance(geom, MultiLineString):
        merged = linemerge(geom)
        if isinstance(merged, LineString):
            return merged
        coords = [c for part in geom.geoms for c in part.coords]
        return LineString(coords) if len(coords) >= 2 else None
    return None


def split_sections(geometry: dict, n: int) -> list[LineString]:
    """N consecutive WGS84 sections of equal length of the closure geometry."""
    line = _one_line(to_metric(from_geojson(geometry)))
    if line is None or line.length <= 0:
        raise invalid("The closure has no line geometry to split into phases.", code="NO_GEOMETRY")
    step = line.length / n
    out = []
    for i in range(n):
        seg = substring(line, i * step, (i + 1) * step)
        if not isinstance(seg, LineString) or seg.length <= 0:
            raise invalid("Could not split the closure geometry.", code="NO_GEOMETRY")
        out.append(to_wgs84(seg))
    return out


def section_keys(closure: dict, section: LineString) -> list[Key]:
    """Lost rows of one section: m1-core's matching on a temporary drawn closure (never stored)."""
    temp = dict(closure)
    temp.update(id=f"{closure['id']}_phase", kind="drawn", geometry=to_geojson(section),
                routeActions=None, temporaryRoutes=None, sourceText=None)
    rows, _ = matching.match_closure(temp)
    return lost_keys(rows)


# --- the suggestion -------------------------------------------------------------------------------


METHOD_RO = ("Ferestrele încep din 30 în 30 de minute în intervalul căutat și au durata lucrării. Pentru fiecare "
             "numărăm, în orarul GTFS, plecările pierdute la stațiile scoase din circulație de lucrare (aceleași "
             "rânduri ca în impact: afectate sau confirmate). Ordinea: mai puține plecări pierdute, apoi mai puține "
             "conflicte cu alte lucrări, apoi mai puțini locuitori fără stație (model GHSL 2020, nu recensământ). "
             "Ferestrele care se suprapun sunt eliminate; rămân primele 10. Estimare pe orarul planificat.")
METHOD_EN = ("Windows start every 30 minutes in the search range and last as long as the works. For each we count, "
             "in the GTFS timetable, the departures lost at the stops the closure takes out (the same rows as the "
             "impact: affected or confirmed). Order: fewer departures lost, then fewer conflicts with other works, "
             "then fewer residents losing their stop (GHSL 2020 model, not a census). Overlapping windows are "
             "removed; the top 10 remain. An estimate on the planned timetable.")


def _same_hours_sentence(closure: dict, costs: np.ndarray, rng: SearchRange) -> tuple[str, str] | None:
    """'La aceeași oră (10:00–18:00): sâmbătă pierde 1.766 plecări, luni 2.116, …' over the first week."""
    if rng.hours > 24:
        return None
    cs = np.concatenate([[0.0], np.cumsum(costs)])
    s0 = parse_iso(closure["window"]["start"])
    h = int(round(rng.hours * 60))
    seen: dict[int, tuple[datetime, int]] = {}
    day = rng.start.date()
    for k in range(8):
        d = day + timedelta(days=k)
        s = datetime(d.year, d.month, d.day, s0.hour, s0.minute, tzinfo=TZ)
        i = int((s - rng.start).total_seconds() // 60)
        if i < 0 or i + h > len(costs) or s.weekday() in seen:
            continue
        seen[s.weekday()] = (s, int(round(cs[i + h] - cs[i])))
    if len(seen) < 2:
        return None
    items = sorted(seen.values(), key=lambda x: x[0])
    first_s = items[0][0]
    hrs = f"{_hm(first_s)}–{_hm(first_s + timedelta(minutes=h))}"
    ro = ", ".join(f"{WEEKDAYS_RO[s.weekday()]} {num_ro(n)}" for s, n in items)
    en = ", ".join(f"{WEEKDAYS_EN[s.weekday()]} {num_en(n)}" for s, n in items)
    return (f"La aceeași oră ca în anunț ({hrs}), plecări pierdute pe zile: {ro}.",
            f"At the notice's hours ({hrs}), departures lost per day: {en}.")


def _candidate_note(c: Candidate, own: int | None, own_span: tuple[str, str]) -> I18n:
    ro = f"{span_ro(c.start, c.end)}: se pierd {num_ro(c.departures)} plecări"
    en = f"{span_en(c.start, c.end)}: {num_en(c.departures)} departures lost"
    if own is not None:
        ro += f", față de {num_ro(own)} în fereastra din anunț ({own_span[0]})"
        en += f", against {num_en(own)} in the notice's window ({own_span[1]})"
    if c.conflicts:
        ro += f"; se suprapune cu {c.conflicts} altă lucrare" if c.conflicts == 1 else \
            f"; se suprapune cu {c.conflicts} alte lucrări"
        en += f"; overlaps {c.conflicts} other works"
    return I18n(ro=ro + ".", en=en + ".")


def own_window_departures(closure: dict, tt: imp.Timetable, keys: list[Key]) -> int | None:
    s, e = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    cw = imp.count_window(s, e, tt)
    counts = imp.departure_counts(cw, tt)
    if counts is None:
        return None
    return int(sum(counts.get(k, 0) for k in keys))


def others_fingerprint() -> str:
    """Hash of the other closures' windows and lost rows (conflicts depend on them), for job keys."""
    parts = []
    for c in state.list_all("closures"):
        a = state.read("closures", c["id"], state.PART_ANALYSIS) or {}
        parts.append((c["id"], c["window"], c.get("geometry"), lost_keys(a.get("stops") or [])))
    blob = json.dumps(sorted(parts, key=lambda p: p[0]), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def suggest(closure_id: str, hours: float | None = None, start: str | None = None, end: str | None = None,
            phases: int = 1) -> WindowSuggestion:
    if not 1 <= int(phases) <= MAX_PHASES:
        raise invalid(f"`phases` must be 1 to {MAX_PHASES}.")
    closure, analysis = load_closure(closure_id)
    return compute(closure, analysis, hours=hours, start=start, end=end, phases=int(phases))


def compute(closure: dict, analysis: dict, hours: float | None = None, start: str | None = None,
            end: str | None = None, phases: int = 1) -> WindowSuggestion:
    tt = imp.timetable_for_closure(closure)
    keys = lost_keys(analysis["stops"])
    rng = search_range(closure, tt, hours, start, end)
    costs = minute_costs(tt, keys, rng.start, rng.end)
    cw = conflict_windows(closure, rng)
    top = rank(candidates(costs, rng, cw), tt, keys)
    if not top:
        raise invalid("No candidate window in the search range.", code="NO_WINDOW")

    own = own_window_departures(closure, tt, keys)
    cs, ce = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    own_span = (span_ro(cs, ce), span_en(cs, ce))
    out_c = [WindowCandidate(window=Window(start=iso(c.start), end=iso(c.end)), departuresLost=c.departures,
                             residentsLosingStop=c.residents, conflicts=c.conflicts, rank=i + 1)
             for i, c in enumerate(top)]
    notes = [_candidate_note(c, own, own_span) for c in top]
    _attach_notes(out_c, notes)

    texts_ro, texts_en = [METHOD_RO], [METHOD_EN]
    best = top[0]
    texts_ro.append(f"Cea mai bună: {notes[0].ro}")
    texts_en.append(f"Best: {notes[0].en}")
    same = _same_hours_sentence(closure, costs, rng)
    if same:
        texts_ro.append(same[0])
        texts_en.append(same[1])
    if cw:
        texts_ro.append("Conflicte numărate cu: " + ", ".join(sorted(x[0] for x in cw)) + ".")
        texts_en.append("Conflicts counted against: " + ", ".join(sorted(x[0] for x in cw)) + ".")

    out_phases = None
    if phases > 1:
        out_phases, ph_ro, ph_en = compute_phases(closure, tt, rng, cw, phases)
        texts_ro.append(ph_ro)
        texts_en.append(ph_en)
    for ro, en in rng.notes:
        texts_ro.append(ro)
        texts_en.append(en)

    return WindowSuggestion(
        closureId=closure["id"], hours=rng.hours, searchFrom=iso(rng.start),
        searchTo=iso(rng.end - timedelta(hours=rng.hours)),
        candidates=out_c, best=Window(start=iso(best.start), end=iso(best.end)), phases=out_phases,
        method=I18n(ro=" ".join(texts_ro), en=" ".join(texts_en)),
        provenance=_provenance(tt, rng, top),
    )


def _attach_notes(cands: list[WindowCandidate], notes: list[I18n]) -> None:
    """Set the optional per-candidate `note` once the model has it (CONTRACT 2.3, additive)."""
    if "note" in WindowCandidate.model_fields:
        for c, n in zip(cands, notes):
            c.note = n


def compute_phases(closure: dict, tt: imp.Timetable, rng: SearchRange,
                   cw: list[tuple[str, datetime, datetime]], n: int) -> tuple[list[WindowPhase], str, str]:
    if not closure.get("geometry"):
        raise invalid("The closure has no geometry to split into phases.", code="NO_GEOMETRY")
    sections = split_sections(closure["geometry"], n)
    taken: list[Candidate] = []
    phases: list[WindowPhase] = []
    ro_parts, en_parts = [], []
    total_m = sum(to_metric(s).length for s in sections)
    for i, sec in enumerate(sections, start=1):
        keys = section_keys(closure, sec)
        costs = minute_costs(tt, keys, rng.start, rng.end)
        best = rank(candidates(costs, rng, cw), tt, keys, top=1, taken=taken)
        if not best:
            raise invalid(f"No free window for phase {i} in the search range.", code="NO_WINDOW")
        b = best[0]
        taken.append(b)
        phases.append(WindowPhase(phase=i, section=to_geojson(sec), window=Window(start=iso(b.start), end=iso(b.end)),
                                  departuresLost=b.departures))
        rows_ro = f"{len(keys)} rânduri stație-linie" if keys else "nicio stație în tronson"
        rows_en = f"{len(keys)} stop-line rows" if keys else "no stop in the section"
        ro_parts.append(f"etapa {i} ({rows_ro}): {span_ro(b.start, b.end)}, {num_ro(b.departures)} plecări")
        en_parts.append(f"phase {i} ({rows_en}): {span_en(b.start, b.end)}, {num_en(b.departures)} departures")
    seg = num_ro(total_m / n)
    return (phases,
            f"Etapizare în {n} tronsoane consecutive de câte ~{seg} m, fiecare cu stațiile lui (potrivire pe "
            f"geometrie, fără acțiunile din anunț) și fereastra lui, fără suprapuneri: " + "; ".join(ro_parts) + ".",
            f"Phasing in {n} consecutive sections of ~{num_en(total_m / n)} m, each with its own stops (matched on "
            f"the geometry, without the notice's actions) and its own window, no overlaps: " + "; ".join(en_parts)
            + ".")


def _provenance(tt: imp.Timetable, rng: SearchRange, top: list[Candidate]) -> list[Provenance]:
    out = [tt.provenance.model_copy(update={"note": (
        f"Plecări pe orarul în vigoare înainte de lucrări, căutare {iso(rng.start)} – {iso(rng.end)}; estimare / "
        f"departures on the timetable in force before the works")})]
    if any(c.residents is not None for c in top):
        out.append(imp.pop_provenance())
    from app.common.provenance import state_provenance

    out.append(state_provenance(now()).model_copy(update={"note": "Conflicte: lucrările din registru / "
                                                                  "conflicts: closures in the register"}))
    return out
