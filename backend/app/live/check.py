"""Live check (SPEC §6.8): did the vehicles really skip the stops a closure suspends?

Input: the closure's affected rows (stop, route, direction) from its stored
Analysis, and our 15 s recording of the city's vehicle feed
($LIVE_DIR/vehicles/YYYYMMDD-HH.jsonl.gz, from 13 Nov 13:47, still growing).
Never a call to the city: the recording only.

A *passage* is one recorded trip of an affected route + direction going past
the place of one affected stop. Each passage gets one state:
- served:  the vehicle reported STOPPED_AT that stop id, or (GPS) it stood
           still (speed <= 1 m/s) within 30 m of the stop;
- skipped: the trip was seen before the stop's place and after it, with no
           served evidence and no gap > 60 s between observations there;
- unknown: a gap > 60 s around the stop's place, or the vehicle dropped out
           of the feed before or after it (not at the recording's edges).

Position along the trip: the recorded trips follow the current GTFS (4.31)
while a closure may count on an older timetable (Mocioni: 4.29, SPEC §5.3),
whose stops the current trips no longer list. So the stop's place is found by
its anchors: the nearest stops before and after it on the timetable the
closure counts on that the recorded trip still lists. "Before" = the vehicle
is at or before the previous anchor; "after" = at or past the next anchor.
A stop the old route started with (no previous anchor) is passed when the
trip leaves its first anchor; one it ended with (no next anchor) when the
trip runs on from its last anchor toward its new end.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from app.common import gtfs, state, vehicles
from app.common import provenance as prov
from app.common.errors import not_found
from app.common.geo import haversine_m
from app.common.timeutil import from_unix, iso, parse_iso
from app.config import TZ, get_settings, real_now
from app.m1_disruption.impact import counts_as_lost, timetable_for_closure

log = logging.getLogger("reteaua_vie.live")

GAP_SEC = 60            # SPEC §6.8: observations more than 60 s apart -> unknown
SERVED_RADIUS_M = 30.0  # GPS: standing within this distance of the stop
STILL_SPEED = 1.0       # m/s; the feed's speed is in m/s (max seen ~22)
TRIP_SPLIT_SEC = 1200   # one trip id seen again after 20 min = another run
EDGE_SEC = 90           # a trip cut by the recording's start or end is not counted
CACHE_VERSION = 1

MONTHS_RO = ("ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sep", "oct", "nov", "dec")
MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

COLUMNS = ["t", "vid", "route", "trip", "dir", "stop", "seq", "stopped", "lat", "lon", "speed", "delay"]


# --- the recording as compact tables (one per UTC hour, cached as Parquet) ----------


def _frame_from_snapshots(snaps: tuple[dict, ...]) -> pd.DataFrame:
    rows = []
    for s in snaps:
        fetched = vehicles.snapshot_time(s).timestamp()
        for v in s.get("vehicles") or []:
            if v.get("lat") is None or v.get("lon") is None or not v.get("routeId"):
                continue
            upd = v.get("updatedAt")
            d = v.get("directionId")
            rows.append((
                int(upd) if isinstance(upd, (int, float)) else int(fetched),
                str(v.get("id")), str(v["routeId"]), str(v.get("tripId") or ""),
                int(d) if d in (0, 1) else -1,
                str(v["stopId"]) if v.get("stopId") is not None else "",
                int(v["stopSequence"]) if isinstance(v.get("stopSequence"), (int, float)) else -1,
                v.get("status") == "STOPPED_AT",
                float(v["lat"]), float(v["lon"]),
                float(v["speed"]) if isinstance(v.get("speed"), (int, float)) else math.nan,
                float(v["delaySec"]) if isinstance(v.get("delaySec"), (int, float)) else math.nan,
            ))
    df = pd.DataFrame(rows, columns=COLUMNS)
    # the feed repeats a vehicle's last report until it sends a new one
    return df.drop_duplicates(["vid", "t"]).reset_index(drop=True)


def _cache_path(path: Path) -> Path:
    stem = path.name[: -len(".jsonl.gz")]
    return get_settings().cache_dir / "live" / f"vehicles_{stem}_v{CACHE_VERSION}.parquet"


@lru_cache(maxsize=128)
def _hour_frame(path_str: str, size: int, mtime: float, closed: bool) -> pd.DataFrame:
    path = Path(path_str)
    cached = _cache_path(path)
    if closed and cached.is_file():
        try:
            return pd.read_parquet(cached)
        except Exception:  # a broken cache file is rebuilt below
            pass
    df = _frame_from_snapshots(vehicles.read_file(path))
    if closed:
        try:  # the data dir may be read-only (Docker api): then memory only
            cached.parent.mkdir(parents=True, exist_ok=True)
            tmp = cached.with_suffix(".tmp")
            df.to_parquet(tmp, index=False)
            tmp.replace(cached)
        except OSError as exc:
            log.info("live cache not written (%s)", exc)
    return df


def recording_frame(start: datetime, end: datetime, routes: set[str] | None = None) -> pd.DataFrame:
    """Every recorded vehicle report with start <= updatedAt < end (unix `t`)."""
    s_utc, e_utc = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    now_utc = real_now().astimezone(timezone.utc)
    parts = []
    for path, hour in vehicles.recording_files():
        # updatedAt may trail fetchedAt: read one hour of margin on each side
        if hour + timedelta(hours=2) <= s_utc or hour - timedelta(hours=1) >= e_utc:
            continue
        st = path.stat()
        closed = hour + timedelta(hours=1, minutes=5) < now_utc
        df = _hour_frame(str(path), st.st_size, st.st_mtime, closed)
        if routes is not None:
            df = df[df["route"].isin(routes)]
        parts.append(df)
    if not parts:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.concat(parts, ignore_index=True)
    df = df[(df["t"] >= int(s_utc.timestamp())) & (df["t"] < int(e_utc.timestamp()))]
    return df.drop_duplicates(["vid", "t"]).sort_values(["vid", "t"], kind="stable").reset_index(drop=True)


def warm_recording() -> int:
    """Build the per-hour cache of every closed hour. Returns the files read."""
    span = vehicles.recording_span()
    if span is None:
        return 0
    recording_frame(span[0] - timedelta(hours=1), span[1] + timedelta(hours=1))
    return len(vehicles.recording_files())


# --- where an affected stop sits on a recorded trip -------------------------------------


@lru_cache(maxsize=2)
def _trip_stops(sha: str) -> dict[str, tuple[str, ...]]:
    st = gtfs.feed().stop_times.sort_values(["trip_id", "stop_sequence"])
    return {t: tuple(s) for t, s in st.groupby("trip_id", sort=False)["stop_id"]}


def trip_stops() -> dict[str, tuple[str, ...]]:
    return _trip_stops(gtfs.feed().sha256)


@dataclass(frozen=True)
class Place:
    """Progress thresholds of one affected stop on one recorded stop list.

    Progress p of a report: index of its stop in the trip's list, minus 0.5
    while IN_TRANSIT_TO it. before: p <= before_max; after: p >= after_min.
    """
    kind: str            # "on_trip" | "between" | "first" | "last"
    before_max: float
    after_min: float


def place_on_trip(stop_id: str, old_order: list[str], trip: tuple[str, ...]) -> Place | None:
    pos = {s: i for i, s in enumerate(trip)}
    if stop_id in pos:
        i = pos[stop_id]
        return Place("on_trip", i - 0.5, i + 0.5)
    if stop_id not in old_order:
        return None
    k = old_order.index(stop_id)
    prev = next((pos[s] for s in reversed(old_order[:k]) if s in pos), None)
    nxt = next((pos[s] for s in old_order[k + 1:] if s in pos), None)
    if prev is not None and nxt is not None:
        return Place("between", prev, nxt) if nxt > prev else None
    if nxt is not None:      # the old route started here; the trip now starts later
        return Place("first", max(nxt - 1, 0), max(nxt, 0.5))
    if prev is not None:     # the old route ended here; the trip now ends earlier
        if prev >= len(trip) - 1:
            return Place("last", prev - 0.5, prev)
        return Place("last", prev, prev + 0.5)
    return None


# --- passages ---------------------------------------------------------------------------------


@dataclass
class Row:
    stop_id: str
    name: str | None
    route_id: str
    direction_id: int
    lon: float
    lat: float
    old_order: list[str]
    counts: dict[str, int] = field(default_factory=lambda: {"skipped": 0, "served": 0, "unknown": 0})


@dataclass
class Passage:
    row: Row
    vid: str
    trip: str
    state: str
    evidence: str | None
    t: int
    delay: float


def _progress(stops: np.ndarray, stopped: np.ndarray, pos: dict[str, int]) -> np.ndarray:
    p = np.array([pos.get(s, np.nan) for s in stops], dtype=float)
    return np.where(stopped, p, p - 0.5)


def _served(seg: pd.DataFrame, row: Row) -> int | None:
    """Index in `seg` of the first served evidence, with its kind; None if none."""
    at_stop = seg["stopped"].to_numpy() & (seg["stop"].to_numpy() == row.stop_id)
    if at_stop.any():
        return int(np.flatnonzero(at_stop)[0])
    lat, lon, spd = seg["lat"].to_numpy(), seg["lon"].to_numpy(), seg["speed"].to_numpy()
    for j in range(len(seg)):
        if spd[j] <= STILL_SPEED and haversine_m(lon[j], lat[j], row.lon, row.lat) <= SERVED_RADIUS_M:
            return -1 - j  # negative = GPS evidence at index j
    return None


def _contiguous(v: pd.DataFrame, t0: int, backward: bool) -> pd.DataFrame:
    """The vehicle's reports right before (or after) t0 with no gap > 60 s, at most 15 min."""
    t = v["t"].to_numpy()
    if backward:
        idx = np.flatnonzero((t < t0) & (t >= t0 - 900))[::-1]
        ref = t0
        keep = []
        for i in idx:
            if ref - t[i] > GAP_SEC:
                break
            keep.append(i)
            ref = t[i]
        return v.iloc[sorted(keep)]
    idx = np.flatnonzero((t > t0) & (t <= t0 + 900))
    ref = t0
    keep = []
    for i in idx:
        if t[i] - ref > GAP_SEC:
            break
        keep.append(i)
        ref = t[i]
    return v.iloc[keep]


def _judge(g: pd.DataFrame, p: np.ndarray, row: Row, place: Place, edges: tuple[int, int],
           vehicle: pd.DataFrame) -> Passage | None:
    t = g["t"].to_numpy()
    before = np.flatnonzero(p <= place.before_max)
    after = np.flatnonzero(p >= place.after_min)
    first_after = None
    if len(after):
        # the first report past the place that follows a report before it, if any
        later = after[after > before[0]] if len(before) else after
        first_after = int(later[0]) if len(later) else int(after[0])
    last_before = None
    if len(before):
        prior = before[before < first_after] if first_after is not None else before
        last_before = int(prior[-1]) if len(prior) else None
    lo = last_before if last_before is not None else 0
    hi = first_after if first_after is not None else len(g) - 1
    parts = [g.iloc[lo:hi + 1]]
    has_before, has_after = last_before is not None, first_after is not None
    # A stop the old route started (ended) with lies before (after) the trip itself:
    # the vehicle's reports just before the trip starts (after it ends) cover it.
    if not has_before and place.kind == "first" and first_after is not None:
        approach = _contiguous(vehicle, int(t[0]), backward=True)
        if len(approach):
            parts.insert(0, approach)
            has_before = True
    if not has_after and place.kind == "last" and last_before is not None:
        follow = _contiguous(vehicle, int(t[-1]), backward=False)
        if len(follow):
            parts.append(follow)
            has_after = True
    seg = pd.concat(parts) if len(parts) > 1 else parts[0]
    vid, trip = str(g["vid"].iloc[0]), str(g["trip"].iloc[0])
    hit = _served(seg, row)
    if hit is not None:
        k = hit if hit >= 0 else -1 - hit
        return Passage(row, vid, trip, "served", "stopped_at" if hit >= 0 else "gps", int(seg["t"].iloc[k]),
                       float(seg["delay"].iloc[k]))
    if has_before and has_after:
        gaps = np.diff(seg["t"].to_numpy())
        state_ = "unknown" if (len(gaps) and gaps.max() > GAP_SEC) else "skipped"
        k = first_after if first_after is not None else len(g) - 1
        return Passage(row, vid, trip, state_, None, int(t[k]), float(g["delay"].iloc[k]))
    if last_before is None and first_after is None:
        return None  # the trip was never seen near this stop's place
    # one side only: cut by the recording's edges = not counted; else the vehicle dropped out
    if not has_after and t[-1] >= edges[1] - EDGE_SEC:
        return None
    if not has_before and t[0] <= edges[0] + EDGE_SEC:
        return None
    k = first_after if first_after is not None else len(g) - 1
    return Passage(row, vid, trip, "unknown", None, int(t[k]), float(g["delay"].iloc[k]))


def passages(rows: list[Row], frame: pd.DataFrame, edges: tuple[int, int]) -> list[Passage]:
    trips = trip_stops()
    patterns = gtfs.stop_patterns()
    by_rd: dict[tuple[str, int], list[Row]] = {}
    for r in rows:
        by_rd.setdefault((r.route_id, r.direction_id), []).append(r)
    out: list[Passage] = []
    if frame.empty:
        return out
    by_vehicle = {vid: v.sort_values("t", kind="stable") for vid, v in frame.groupby("vid", sort=False)}
    frame = frame[frame["dir"] >= 0]
    place_memo: dict[tuple[str, int, str, tuple[str, ...]], Place | None] = {}
    for (route, d, vid, trip), g in frame.groupby(["route", "dir", "vid", "trip"], sort=False):
        rds = by_rd.get((route, int(d)))
        if not rds or not trip:
            continue
        stops = trips.get(trip)
        if stops is None:
            pat = patterns.get((route, int(d)))
            stops = pat.stop_ids if pat else ()
        if not stops:
            continue
        pos = {s: i for i, s in enumerate(stops)}
        g = g.sort_values("t", kind="stable")
        # one trip id runs every day: split runs at long gaps
        t = g["t"].to_numpy()
        cuts = np.flatnonzero(np.diff(t) > TRIP_SPLIT_SEC) + 1
        for run in np.split(np.arange(len(g)), cuts):
            gr = g.iloc[run]
            p = _progress(gr["stop"].to_numpy(), gr["stopped"].to_numpy(), pos)
            ok = ~np.isnan(p)
            if not ok.any():
                continue
            gr, p = gr[ok], p[ok]
            for row in rds:
                key = (row.stop_id, row.direction_id, route, stops)
                if key not in place_memo:
                    place_memo[key] = place_on_trip(row.stop_id, row.old_order, stops)
                place = place_memo[key]
                if place is None:
                    continue
                ps = _judge(gr, p, row, place, edges, by_vehicle[vid])
                if ps is not None:
                    out.append(ps)
    out.sort(key=lambda x: (x.t, x.row.route_id, x.row.stop_id, x.vid))
    return out


# --- the response ---------------------------------------------------------------------------


def period_label(start: datetime, end: datetime) -> dict:
    """„Înregistrare reală, 13–14 nov” for the period shown on screen."""
    s, e = start.astimezone(TZ), end.astimezone(TZ)

    def span(months: tuple[str, ...]) -> str:
        if (s.year, s.month, s.day) == (e.year, e.month, e.day):
            return f"{s.day} {months[s.month - 1]}"
        if (s.year, s.month) == (e.year, e.month):
            return f"{s.day}–{e.day} {months[s.month - 1]}"
        return f"{s.day} {months[s.month - 1]} – {e.day} {months[e.month - 1]}"

    return {"ro": f"Înregistrare reală, {span(MONTHS_RO)}", "en": f"Real recording, {span(MONTHS_EN)}"}


METHOD = {
    "ro": ("Pentru fiecare cursă înregistrată a unei linii afectate (la 15 s) verificăm locul fiecărei "
           "stații afectate pe traseu. Sărită: vehiculul e văzut înainte și după locul stației, fără oprire "
           "acolo și fără pauză de peste 60 s între raportări. Deservită: raportează STOPPED_AT la stație "
           "sau stă pe loc la cel mult 30 m de ea (GPS). Necunoscut: pauză de peste 60 s sau vehiculul "
           "dispare din flux. Cursele înregistrate urmează orarul GTFS curent, iar stațiile suspendate vin "
           "din orarul de dinainte de lucrări, așa că locul stației se găsește după stațiile vecine pe care "
           "cursa le mai are. O trecere = o cursă pe lângă o stație afectată."),
    "en": ("For each recorded trip of an affected line (15 s polls) we locate each affected stop on its "
           "path. Skipped: the vehicle is seen before and after the stop's place, with no stop there and "
           "no gap over 60 s between reports. Served: it reports STOPPED_AT the stop or stands still within "
           "30 m of it (GPS). Unknown: a gap over 60 s or the vehicle drops out of the feed. Recorded trips "
           "follow the current GTFS while the suspended stops come from the timetable before the works, so "
           "the stop's place is found from the neighbouring stops the trip still has. One passage = one "
           "trip past one affected stop."),
}


def _rows(closure: dict, analysis: dict) -> list[Row]:
    tt = timetable_for_closure(closure)
    old = tt.stop_patterns()
    cur = gtfs.stop_patterns()
    out = []
    for s in analysis.get("stops") or []:
        if not counts_as_lost(s):
            continue
        key = (s["routeId"], int(s["directionId"]))
        order = list(old[key].stop_ids) if key in old else []
        if s["stopId"] not in order and key in cur:
            order = list(cur[key].stop_ids)
        lon, lat = s["location"][0], s["location"][1]
        out.append(Row(s["stopId"], s.get("name"), s["routeId"], int(s["directionId"]), float(lon), float(lat),
                       order))
    return out


def compute_live_check(closure_id: str) -> dict:
    """LiveCheck (CONTRACT, + v2.3 optional fields) for one stored closure."""
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id!r}.")
    analysis = state.read("closures", closure_id, state.PART_ANALYSIS)
    if analysis is None:
        raise not_found(f"Closure {closure_id!r} has no analysis yet: analyze it first.", "NOT_ANALYZED")
    ws, we = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    span = vehicles.recording_span()
    rows = _rows(closure, analysis)
    base = {"closureId": closure_id, "from": iso(ws), "to": iso(we), "observations": [], "byStop": None,
            "recordedFrom": iso(span[0]) if span else None, "recordedTo": iso(span[1]) if span else None,
            "method": METHOD}
    empty_summary = {"vehiclesSeen": None, "stopsSkipped": None, "stopsServedAnyway": None, "stopsUnknown": None}

    if span is None or we <= span[0] or ws >= span[1]:
        rec = (f"înregistrarea noastră acoperă {iso(span[0])} – {iso(span[1])}" if span
               else "nu există încă înregistrare")
        rec_en = (f"our recording covers {iso(span[0])} – {iso(span[1])}" if span else "no recording yet")
        note = {"ro": f"Nu avem vehicule înregistrate în fereastra lucrării ({iso(ws)} – {iso(we)}): {rec}. "
                      "Stațiile sărite sunt necunoscute, nu zero.",
                "en": f"No recorded vehicles inside the closure window: {rec_en}. Skipped stops are unknown, "
                      "not zero."}
        p = prov.vehicles_provenance(span[1] if span else real_now(), note["en"])
        return {**base, "source": None, "summary": empty_summary, "label": None, "note": note,
                "provenance": [p.model_dump()]}

    start, end = max(ws, span[0]), min(we, span[1])
    if not rows:
        note = {"ro": "Lucrarea nu are stații afectate confirmate: nu avem ce verifica.",
                "en": "The closure has no confirmed affected stops: nothing to check."}
        return {**base, "from": iso(start), "to": iso(end), "source": "replay", "summary": empty_summary,
                "byStop": [], "label": period_label(start, end), "note": note,
                "provenance": [prov.vehicles_provenance(end, note["en"]).model_dump()]}

    routes = {r.route_id for r in rows}
    frame = recording_frame(start, end + timedelta(seconds=1), routes)
    edges = (int(span[0].timestamp()), int(span[1].timestamp()))
    found = passages(rows, frame, edges)
    for ps in found:
        ps.row.counts[ps.state] += 1
    observations = [{
        "vehicleId": ps.vid, "routeId": ps.row.route_id, "tripId": ps.trip or None,
        "directionId": ps.row.direction_id, "stopId": ps.row.stop_id, "served": ps.state == "served",
        "seenAt": iso(from_unix(ps.t)), "delaySec": None if math.isnan(ps.delay) else int(ps.delay),
        "state": ps.state, "evidence": ps.evidence,
    } for ps in found]
    n = {k: sum(1 for ps in found if ps.state == k) for k in ("skipped", "served", "unknown")}
    summary = {"vehiclesSeen": len({ps.vid for ps in found}), "stopsSkipped": n["skipped"],
               "stopsServedAnyway": n["served"], "stopsUnknown": n["unknown"]}
    by_stop = [{"stopId": r.stop_id, "name": r.name, "routeId": r.route_id, "directionId": r.direction_id,
                **r.counts} for r in rows]
    tt = timetable_for_closure(closure)
    note_ro = (f"Perioada verificată: {iso(start)} – {iso(end)}, {len(frame)} raportări ale liniilor "
               f"{', '.join(sorted(routes))}. Stațiile afectate vin din GTFS {tt.version}, cursele "
               f"înregistrate urmează GTFS {gtfs.feed().version}.")
    note_en = (f"Checked period {iso(start)} – {iso(end)}, {len(frame)} vehicle reports. Affected stops come "
               f"from GTFS {tt.version}; recorded trips follow GTFS {gtfs.feed().version}.")
    provenance = [
        prov.vehicles_provenance(end, f"Înregistrare reală / real recording, {iso(start)} – {iso(end)}, "
                                          f"la 15 s / every 15 s").model_dump(),
        gtfs.feed().provenance.model_dump(),
    ]
    if tt.history:
        provenance.append(tt.provenance.model_dump())
    return {**base, "from": iso(start), "to": iso(end), "source": "replay", "observations": observations,
            "summary": summary, "byStop": by_stop, "label": period_label(start, end),
            "note": {"ro": note_ro, "en": note_en}, "provenance": provenance}
