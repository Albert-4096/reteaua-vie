"""M4 access: residents who reach a hospital / school / rail station in N minutes, before vs. with the closure.

SPEC §6.4 "Access":
- Destinations: OSM (layers.py): hospital polygons, schools, rail stations.
- Origins: GHSL 2020 cells inside the 40 neighbourhoods. For speed, cells are grouped
  in blocks of BLOCK x BLOCK cells (200 m); R5 routes from each block's
  population-weighted centre, and every cell of the block gets the block's answer.
  Each cell keeps its own neighbourhood for the totals.
- Router: R5 (r5py), walk + transit, walk 4.8 km/h, at most 15 min of walking,
  travel time = median over a 10-minute departure window, max trip = `minutes`.
- `at`: the window start if it is in daytime service (06:00-21:00, a departure within
  30 min), else the next
  weekday 08:00 inside the window, else the first half hour of the window with
  service (SPEC: "the window start if it falls inside service, else the next weekday 08:00").
- Before = the timetable in force before the works (impact.timetable_for); after =
  the patched GTFS (patched_gtfs.py). A block reaches a destination if any
  destination is within `minutes`.
- residentsLosing = residents of cells that reach a destination before and not after.
  Removing trips never makes a trip faster, so "after" is only computed for blocks
  that reach before.
- Always `estimate: true`.

The "before" reach is cached on disk per (base feed, dest, minutes, at); the whole
AccessImpact is cached by the job helper (api_access.py).

Public:
    compute_access(closure_id, dest, minutes) -> AccessImpact
    access_for(closure, lost, dest, minutes, frequencies=None) -> AccessImpact   (scenarios)
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.common import provenance as prov
from app.common.city import load_zones
from app.common.errors import invalid
from app.common.timeutil import iso, parse_iso
from app.config import TZ, get_settings, now
from app.m1_disruption import impact as imp
from app.m4_access import layers, patched_gtfs, r5
from app.models.base import I18n, Provenance
from app.models.v2 import AccessImpact, AccessTotals, AccessZone

log = logging.getLogger("reteaua_vie.access")

DESTS = layers.DEST_KINDS
BLOCK = 2                     # cells per block side: 2 x 100 m
ACCESS_VERSION = 2            # bump when the method changes (cache keys)
SERVICE_PROBE_MIN = 30        # "inside service": a departure within 30 min of the time
WEEKDAY_HOUR = 8
DAY_FROM_HOUR, DAY_TO_HOUR = 6, 21

_lock = threading.Lock()

DEST_NAMES = {
    "hospital": ("un spital", "a hospital"),
    "school": ("o școală", "a school"),
    "rail_station": ("o gară", "a rail station"),
    "landmark": ("un obiectiv din ghidul turistic al Primăriei", "a landmark from the City Hall's tourist guide"),
}


# --- origins ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Origins:
    block_id: np.ndarray          # (B,) str
    lon: np.ndarray               # (B,) population-weighted centre
    lat: np.ndarray
    cell_block: np.ndarray        # (C,) index into blocks, per cell inside the 40 zones
    cell_residents: np.ndarray    # (C,)
    cell_zone: np.ndarray         # (C,) index into load_zones().slugs


@lru_cache(maxsize=1)
def origins() -> Origins:
    cells = layers.population_cells()
    inside = cells.zone >= 0
    rc = np.array([[int(c[1:].split("c")[0]), int(c.split("c")[1])] for c in cells.cell_id[inside]],
                  dtype=np.int64).reshape(-1, 2)
    keys = [f"b{r // BLOCK}_{c // BLOCK}" for r, c in rc]
    block_ids, cell_block = np.unique(np.array(keys), return_inverse=True)
    res = cells.residents[inside]
    w = np.bincount(cell_block, weights=res, minlength=len(block_ids))
    lon = np.bincount(cell_block, weights=res * cells.lon[inside], minlength=len(block_ids)) / w
    lat = np.bincount(cell_block, weights=res * cells.lat[inside], minlength=len(block_ids)) / w
    return Origins(block_ids, lon, lat, cell_block, res, cells.zone[inside])


# --- the departure time ----------------------------------------------------------------------


def _has_service(tt: imp.Timetable, t: datetime) -> bool:
    """Daytime service at t: 06:00-21:00 and a departure within 30 min (a few night trips do not count)."""
    local = t.astimezone(TZ)
    first, last = tt.coverage()
    if not (first <= local.date() <= last) or not (DAY_FROM_HOUR <= local.hour < DAY_TO_HOUR):
        return False
    return bool(tt.counts(t, t + timedelta(minutes=SERVICE_PROBE_MIN)))


def choose_at(start: datetime, end: datetime, tt: imp.Timetable) -> datetime:
    """SPEC §6.4: the window start if inside service, else the next weekday 08:00 (inside the window)."""
    start, end = start.astimezone(TZ), end.astimezone(TZ)
    if _has_service(tt, start):
        return start
    d = start.date()
    for _ in range(14):
        cand = datetime(d.year, d.month, d.day, WEEKDAY_HOUR, tzinfo=TZ)
        if cand >= start and cand.weekday() < 5:
            if cand < end and _has_service(tt, cand):
                return cand
            break
        d += timedelta(days=1)
    t = start
    while t < end and t < start + timedelta(days=7):
        if _has_service(tt, t):
            return t
        t += timedelta(minutes=30)
    return start


# --- reach ------------------------------------------------------------------------------------


def _dest_frame(dest: str):
    ds = layers.destinations(dest)
    if not ds:
        raise invalid(f"No `{dest}` in the OSM extract.", code="NO_DESTINATIONS")
    return r5.points_frame([d.osmId for d in ds], [d.lon for d in ds], [d.lat for d in ds])


def reach(gtfs_zip: Path, dest: str, minutes: int, at: datetime, mask: np.ndarray | None = None) -> np.ndarray:
    """Bool per origin block: some `dest` within `minutes` (walk + transit). Blocks off `mask` are False."""
    o = origins()
    sel = np.arange(len(o.block_id)) if mask is None else np.nonzero(mask)[0]
    out = np.zeros(len(o.block_id), dtype=bool)
    if len(sel) == 0:
        return out
    frame = r5.points_frame(o.block_id[sel].tolist(), o.lon[sel], o.lat[sel])
    tt = r5.travel_times(gtfs_zip, frame, _dest_frame(dest), at, minutes)
    best = tt.groupby("from_id")["travel_time"].min()
    ok = set(best[best <= minutes].index)
    out[sel] = [b in ok for b in o.block_id[sel]]
    return out


def _before_cache(base_zip: Path, dest: str, minutes: int, at: datetime) -> Path:
    key = json.dumps([ACCESS_VERSION, BLOCK, base_zip.name, dest, minutes, iso(at)])
    d = get_settings().cache_dir / "r5" / "access"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"before_{hashlib.sha256(key.encode()).hexdigest()[:20]}.npy"


def reach_before(base_zip: Path, dest: str, minutes: int, at: datetime) -> np.ndarray:
    path = _before_cache(base_zip, dest, minutes, at)
    if path.is_file():
        arr = np.load(path)
        if len(arr) == len(origins().block_id):
            return arr
    arr = reach(base_zip, dest, minutes, at)
    with _lock:
        tmp = path.with_name(path.stem + ".tmp.npy")
        np.save(tmp, arr)
        tmp.replace(path)
    return arr


# --- the AccessImpact --------------------------------------------------------------------------

def method_text(dest: str, minutes: int) -> I18n:
    ro_d, en_d = DEST_NAMES[dest]
    src_ro, src_en = (("din api/mobile/pois al Primăriei", "from the City Hall api/mobile/pois") if dest == "landmark"
                      else ("din OpenStreetMap", "from OpenStreetMap"))
    return I18n(
        ro=(f"Estimare: locuitori care ajung la {ro_d} în cel mult {minutes} de minute, pe jos și cu transportul "
            f"public, după orarul planificat (GTFS), înainte de lucrare și cu lucrarea (orarul fără plecările "
            f"suspendate în fereastră). Rutare R5 (r5py): mers pe jos 4,8 km/h, cel mult 15 minute de mers, "
            f"mediana pe 10 minute de plecare. Populația: model GHSL 2020, 100 m (nu recensământ), grupat în "
            f"blocuri de 200 m. Destinații {src_ro}."),
        en=(f"Estimate: residents who reach {en_d} within {minutes} minutes by walking and public transport on "
            f"the planned timetable (GTFS), before the works and with them (timetable without the suspended "
            f"departures in the window). R5 routing (r5py): walking 4.8 km/h, at most 15 minutes of walking, "
            f"median over a 10-minute departure window. Population: GHSL 2020 100 m model (not a census), "
            f"grouped in 200 m blocks. Destinations {src_en}."),
    )


def _r5_provenance(pf: patched_gtfs.PatchedFeed, at: datetime) -> Provenance:
    note = (f"estimare; plecare {iso(at)}; {len(pf.lost)} perechi stație–linie suspendate, "
            f"{pf.trips_split} curse modificate, {pf.trips_cancelled} curse anulate în fereastră")
    if pf.trips_added:
        note += f"; {pf.trips_added} curse adăugate (măsură de frecvență)"
    if pf.frequency_notes:
        note += "; " + "; ".join(pf.frequency_notes)
    return prov.provenance(
        "Rețeaua Vie: R5 (Conveyal, r5py) pe GTFS cu plecările suspendate scoase / patched GTFS",
        now(), "https://r5py.readthedocs.io", None, note)


def access_for(closure: dict, lost: set[tuple[str, str, int]], dest: str = "hospital", minutes: int = 30,
               frequencies: list[dict] | None = None) -> AccessImpact:
    """AccessImpact of a closure dict (needs `id`, `window`) and its lost (stop, route, dir) rows.

    For scenarios too (never stored). `frequencies` = [{"routeId", "headwayMinutes"}].
    """
    if dest not in DESTS:
        raise invalid(f"`dest` must be one of {', '.join(DESTS)}.")
    if not 15 <= int(minutes) <= 60:
        raise invalid("`minutes` must be between 15 and 60.")
    minutes = int(minutes)
    pf = patched_gtfs.patched_for(closure, set(lost), frequencies)
    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    tt = imp.timetable_for(start)
    at = choose_at(start, end, tt)

    before = reach_before(pf.base_path, dest, minutes, at)
    changed = bool(pf.lost) or bool(pf.trips_added)
    after = reach(pf.path, dest, minutes, at, mask=None if pf.trips_added else before) if changed else before.copy()

    o = origins()
    cb = before[o.cell_block]
    ca = after[o.cell_block]
    z = load_zones()
    n = len(z.slugs)
    res_b = np.bincount(o.cell_zone, weights=o.cell_residents * cb, minlength=n)
    res_l = np.bincount(o.cell_zone, weights=o.cell_residents * (cb & ~ca), minlength=n)
    res_g = np.bincount(o.cell_zone, weights=o.cell_residents * (~cb & ca), minlength=n)   # added trips only
    rows = []
    for i, slug in enumerate(z.slugs):
        rb, rl, rg = int(round(res_b[i])), int(round(res_l[i])), int(round(res_g[i]))
        rows.append(AccessZone(slug=slug, name=z.names.get(slug, slug), residentsBefore=rb,
                               residentsAfter=rb - rl + rg, residentsLosing=rl))
    rows.sort(key=lambda r: (-(r.residentsLosing or 0), r.name))
    totals = AccessTotals(residentsBefore=sum(r.residentsBefore for r in rows),
                          residentsAfter=sum(r.residentsAfter for r in rows),
                          residentsLosing=sum(r.residentsLosing for r in rows))
    provenance = [tt.provenance, layers.osm_provenance(), imp.pop_provenance(), z.provenance,
                  _r5_provenance(pf, at)]
    if dest == "landmark" and (lm := layers.load_landmarks()) is not None:
        provenance.insert(1, lm[1])
    return AccessImpact(closureId=str(closure.get("id") or ""), dest=dest, minutes=minutes, at=iso(at),
                        totals=totals, byZone=rows, estimate=True, method=method_text(dest, minutes),
                        provenance=provenance)


def access_key(closure: dict, lost: set[tuple[str, str, int]], dest: str, minutes: int,
               frequencies: list[dict] | None = None) -> str:
    """Job-cache key from what the result depends on: the window and the lost rows (not who decided them).

    So decisions taken live (D-012) hit a result pre-computed for the same rows.
    """
    blob = json.dumps([closure["window"], sorted(lost), frequencies or []], sort_keys=True)
    h = hashlib.sha256(blob.encode()).hexdigest()[:16]
    return f"access:v{ACCESS_VERSION}:{closure.get('id')}:{dest}:{int(minutes)}:{h}"


def compute_access(closure_id: str, dest: str = "hospital", minutes: int = 30) -> AccessImpact:
    """AccessImpact of a stored closure with its current decisions."""
    closure, lost = patched_gtfs.lost_rows(closure_id)
    return access_for(closure, lost, dest, minutes)
