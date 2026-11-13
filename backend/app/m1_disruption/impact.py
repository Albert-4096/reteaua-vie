"""Impact of a closure (SPEC §6.1 items 8-9, §6.4 residentsLosingStop).

- Departures lost: GTFS departures of each lost (stop, route, direction) row
  inside window ∩ the service days the feed covers (foundation's index).
- stopsSuspended: lost stops with no remaining departure of any route.
- Nearest served stop: walking distance on the OSM pedestrian graph
  (pyrosm, cached in $DATA_DIR/cache); straight line × 1.3 when the graph
  cannot connect the two stops ("aproximativ").
- residentsLosingStop: GHSL 2020 cells within 400 m of a suspended stop with
  no served stop within 400 m; aggregated per zone.

Which rows count (CONTRACT: "unsure stops count only after a decision"):
`affected` rows unless a person unticked them, `unsure` rows only when ticked.

Public: compute_impact(closure_id) -> Impact, plus the helpers analysis.py
uses to fill departuresLost and nearestServed on each row.
"""

from __future__ import annotations

import hashlib
import heapq
import io
import json
import logging
import math
import threading
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import shapely
from shapely import STRtree

from app.common import gtfs, state
from app.common import provenance as prov
from app.common.city import load_network, load_zones, zone_for_point
from app.common.errors import invalid, not_found
from app.common.geo import project_lonlats
from app.common.timeutil import from_unix, gtfs_service_start, iso, local_midnight, parse_iso
from app.config import TZ, get_settings, now
from app.models.base import I18n, Provenance, Window
from app.models.v1 import Impact, ImpactTotals, ZoneImpact

log = logging.getLogger("reteaua_vie.impact")

Key = tuple[str, str, int]

NEAREST_MAX_M = 1500.0          # SPEC §6.1 item 9
SAME_ROUTE_SLACK_M = 400.0      # prefer the same route + direction if at most this much farther
WALK_CUTOFF_M = 3000.0          # Dijkstra radius (walking >= straight line)
APPROX_FACTOR = 1.3             # straight line × 1.3 when the graph fails
RESIDENT_RADIUS_M = 400.0       # SPEC §6.4
WALK_CACHE_VERSION = 1
OUTSIDE_SLUG = "_outside"
OUTSIDE_NAME = "În afara celor 40 de cartiere / outside the 40 neighbourhoods"

GHSL_LABEL = "model GHSL 2020, 100 m (nu recensământ)"
POP_FILE = "pop/ghsl_2020_100m.tif"
OSM_FILE = "osm/timisoara.osm.pbf"


# --- which rows count ----------------------------------------------------------


def counts_as_lost(row: dict) -> bool:
    if row["state"] == "affected":
        return row.get("confirmed") is not False
    return row.get("confirmed") is True


def row_key(row: dict) -> Key:
    return (row["stopId"], row["routeId"], int(row["directionId"]))


# --- which timetable: the one in force before the works ------------------------------
#
# Departures lost are counted on the timetable that would have run without the
# closure (SPEC §5.3): the newest GTFS feed whose start date is strictly before
# the closure starts. Usually that is the current feed (foundation's index).
# When STPT already published the diverted timetable on the first day of the
# works (Mocioni: 4.30 from 2 Nov), an older feed from $DATA_DIR/gtfs-history/
# is used (4.29), counted here directly from its stop_times.

HISTORY_DIR = "gtfs-history"


def _read_csv(z: zipfile.ZipFile, name: str) -> pd.DataFrame:
    if name not in z.namelist():
        return pd.DataFrame()
    return pd.read_csv(io.StringIO(z.read(name).decode("utf-8-sig")), dtype=str, keep_default_na=False)


def _ymd(v: str) -> date:
    return datetime.strptime(v, "%Y%m%d").date()


@lru_cache(maxsize=16)
def _feed_start(path_str: str, mtime: float) -> tuple[date | None, str | None]:
    with zipfile.ZipFile(path_str) as z:
        info = _read_csv(z, "feed_info.txt")
    if not len(info):
        return None, None
    start = info["feed_start_date"].iloc[0] if "feed_start_date" in info else ""
    return (_ymd(start) if start else None), (info["feed_version"].iloc[0] if "feed_version" in info else None)


class Timetable:
    """The current GTFS feed (foundation's departure index)."""

    history = False

    @property
    def version(self) -> str | None:
        return gtfs.feed().version

    def stop_patterns(self) -> dict[tuple[str, int], gtfs.Pattern]:
        return gtfs.stop_patterns()

    def stop_order(self, route_id: str, direction_id: int) -> list[str]:
        p = self.stop_patterns().get((route_id, int(direction_id)))
        return list(p.stop_ids) if p else []

    def coverage(self) -> tuple[date, date]:
        return gtfs.coverage()

    def counts(self, start: datetime, end: datetime) -> dict[Key, int]:
        return _counts(int(start.timestamp()), int(end.timestamp()))

    @property
    def provenance(self) -> Provenance:
        return gtfs.feed().provenance


class HistoryTimetable(Timetable):
    """An older SMTT GTFS zip from $DATA_DIR/gtfs-history/, counted without an index."""

    history = True

    def __init__(self, path: Path):
        self.path = path
        with zipfile.ZipFile(path) as z:
            t = {n: _read_csv(z, f"{n}.txt") for n in ("trips", "stop_times", "calendar", "calendar_dates")}
        self._version = _feed_start(str(path), path.stat().st_mtime)[1]
        st, trips = t["stop_times"], t["trips"]
        trips["direction_id"] = trips["direction_id"].replace("", "0").astype(int)
        st["stop_sequence"] = st["stop_sequence"].astype(int)
        hms = st["departure_time"].str.split(":", expand=True).astype(int)
        st["dep_sec"] = hms[0] * 3600 + hms[1] * 60 + hms[2]
        st = st.sort_values(["trip_id", "stop_sequence"])
        # patterns: the most common stop sequence per (route, direction)
        seqs = st.groupby("trip_id", sort=False)["stop_id"].agg(tuple)
        self._patterns: dict[tuple[str, int], gtfs.Pattern] = {}
        tr = trips.set_index("trip_id")
        for (route, direction), grp in tr.groupby(["route_id", "direction_id"]):
            cnt = Counter(seqs[t] for t in grp.index if t in seqs.index)
            if not cnt:
                continue
            stops, n = cnt.most_common(1)[0]
            heads = grp.loc[[t for t in grp.index if seqs.get(t) == stops], "trip_headsign"]
            self._patterns[(route, int(direction))] = gtfs.Pattern(
                route_id=route, direction_id=int(direction), stop_ids=stops,
                headsign=heads.mode().iloc[0] if len(heads) else "", trips=n, share=n / sum(cnt.values()))
        # departures only (not the last stop of a trip)
        last = st.groupby("trip_id")["stop_sequence"].transform("max")
        dep = st[st["stop_sequence"] < last].merge(trips[["trip_id", "route_id", "direction_id", "service_id"]],
                                                   on="trip_id")
        keys = list(zip(dep["stop_id"], dep["route_id"], dep["direction_id"].astype(int)))
        self._key_code, self._keys = pd.factorize(pd.Series(keys, dtype=object))
        self._svc_code, svc_names = pd.factorize(dep["service_id"])
        self._svc_index = {name: i for i, name in enumerate(svc_names)}
        self._dep_sec = dep["dep_sec"].to_numpy(dtype=np.int64)
        # service dates: calendar + calendar_dates
        days: dict[date, set[str]] = {}
        wd = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        for row in t["calendar"].itertuples(index=False):
            d, e = _ymd(row.start_date), _ymd(row.end_date)
            while d <= e:
                if getattr(row, wd[d.weekday()]) == "1":
                    days.setdefault(d, set()).add(row.service_id)
                d += timedelta(days=1)
        for row in t["calendar_dates"].itertuples(index=False):
            d = _ymd(row.date)
            (days.setdefault(d, set()).add if row.exception_type == "1" else days.setdefault(d, set()).discard)(
                row.service_id)
        self._days = {d: s for d, s in days.items() if s}
        self._memo: dict[tuple[int, int], dict[Key, int]] = {}

    @property
    def version(self) -> str | None:
        return self._version

    def stop_patterns(self) -> dict[tuple[str, int], gtfs.Pattern]:
        return self._patterns

    def coverage(self) -> tuple[date, date]:
        ds = sorted(self._days)
        return ds[0], ds[-1]

    def counts(self, start: datetime, end: datetime) -> dict[Key, int]:
        memo_key = (int(start.timestamp()), int(end.timestamp()))
        if memo_key in self._memo:
            return self._memo[memo_key]
        acc = np.zeros(len(self._keys), dtype=np.int64)
        d = start.astimezone(TZ).date() - timedelta(days=1)  # trips past 24:00 of the day before
        while d <= end.astimezone(TZ).date():
            active = [self._svc_index[s] for s in self._days.get(d, ()) if s in self._svc_index]
            if active:
                base = gtfs_service_start(d)
                lo, hi = (start - base).total_seconds(), (end - base).total_seconds()
                mask = np.isin(self._svc_code, active) & (self._dep_sec >= lo) & (self._dep_sec < hi)
                acc += np.bincount(self._key_code[mask], minlength=len(self._keys))
            d += timedelta(days=1)
        out = {(str(k[0]), str(k[1]), int(k[2])): int(n) for k, n in zip(self._keys, acc) if n}
        self._memo[memo_key] = out
        return out

    @property
    def provenance(self) -> Provenance:
        p = prov.from_sources(f"gtfs-history:{self.path.name}")
        if p is None:
            p = prov.for_file("SMTT GTFS (orar planificat / planned timetable)", self.path, gtfs_url(), self.version)
        note = (f"Orarul în vigoare înainte de lucrări (GTFS {self.version}, {self.path.name}); "
                f"orarul curent rulează deja ocolirea / timetable in force before the works")
        return p.model_copy(update={"note": note, "version": p.version or self.version})


def gtfs_url() -> str:
    return prov.SMTT_GTFS_URL


@lru_cache(maxsize=4)
def _history(path_str: str, mtime: float) -> HistoryTimetable:
    return HistoryTimetable(Path(path_str))


_CURRENT = Timetable()


def current_timetable() -> Timetable:
    return _CURRENT


def timetable_for(window_start: datetime | str | None) -> Timetable:
    """The timetable in force before the works: newest feed starting strictly before the window."""
    if window_start is None:
        return _CURRENT
    day = (parse_iso(window_start) if isinstance(window_start, str) else window_start).astimezone(TZ).date()
    cur = gtfs.feed()
    if cur.start is None or cur.start < day:
        return _CURRENT
    best: tuple[date, Path] | None = None
    hist = get_settings().data_dir / HISTORY_DIR
    for z in sorted(hist.glob("*.zip")) if hist.is_dir() else []:
        start, _ = _feed_start(str(z), z.stat().st_mtime)
        if start is not None and start < day and (best is None or start > best[0]):
            best = (start, z)
    if best is None:
        return _CURRENT  # nothing older: count on the current feed (coverage note says what is missing)
    return _history(str(best[1]), best[1].stat().st_mtime)


def timetable_for_closure(closure: dict) -> Timetable:
    return timetable_for((closure.get("window") or {}).get("start"))


# --- departures in the window ----------------------------------------------------


@dataclass(frozen=True)
class CountWindow:
    start: datetime | None      # None: the window lies outside the feed
    end: datetime | None
    note: str | None


def count_window(start: datetime, end: datetime, tt: Timetable | None = None) -> CountWindow:
    """window ∩ the service days of the timetable, with a note when it is cut."""
    first, last = (tt or _CURRENT).coverage()
    lo = local_midnight(first)
    hi = local_midnight(last + timedelta(days=1))
    s, e = max(start, lo), min(end, hi)
    if s >= e:
        return CountWindow(None, None, f"Fereastra este în afara orarului GTFS ({first} – {last}): "
                                       f"plecări necunoscute / window outside the GTFS feed")
    note = None
    if s > start or e < end:
        note = (f"Plecări numărate doar {iso(s)} – {iso(e)}: orarul GTFS acoperă {first} – {last} / "
                f"departures counted only inside the GTFS feed period")
    return CountWindow(s, e, note)


@lru_cache(maxsize=32)
def _counts(start_ts: int, end_ts: int) -> dict[Key, int]:
    df = gtfs.departures(from_unix(start_ts), from_unix(end_ts))
    if df.empty:
        return {}
    g = df.groupby(["stop_id", "route_id", "direction_id"], observed=True).size()
    return {(str(s), str(r), int(d)): int(n) for (s, r, d), n in g.items() if n}


def departure_counts(cw: CountWindow, tt: Timetable | None = None) -> dict[Key, int] | None:
    """{(stop, route, dir): departures} in the counting window; None when unknown."""
    if cw.start is None:
        return None
    return (tt or _CURRENT).counts(cw.start, cw.end)


def timetable_provenance(tt: Timetable, cw: CountWindow) -> Provenance:
    p = tt.provenance
    if cw.note:
        p = p.model_copy(update={"note": f"{p.note or ''}; {cw.note}".strip("; ")})
    return p


@dataclass
class ServiceState:
    """Who still serves which stop in the window, given the lost rows."""
    counts: dict[Key, int] | None
    lost: set[Key]
    remaining: dict[str, dict[tuple[str, int], int]] = field(default_factory=dict)

    @classmethod
    def build(cls, counts: dict[Key, int] | None, lost: set[Key]) -> "ServiceState":
        st = cls(counts, lost)
        for (s, r, d), n in (counts or {}).items():
            if n > 0 and (s, r, d) not in lost:
                st.remaining.setdefault(s, {})[(r, d)] = n
        return st

    def served(self, stop_id: str, without: tuple[str, int] | None = None) -> set[tuple[str, int]]:
        keys = set(self.remaining.get(stop_id, {}))
        if without is not None:
            keys.discard(without)
        return keys

    def suspended_stops(self) -> set[str]:
        if self.counts is None:
            return set()
        return {s for (s, _, _) in self.lost if not self.remaining.get(s)}


# --- walking graph (OSM pedestrian network) ----------------------------------------------


@dataclass(frozen=True)
class WalkGraph:
    adj: list[list[tuple[int, float]]]   # node -> [(neighbour, metres)]
    node_xy: np.ndarray                  # (N, 2) metric
    tree: STRtree
    edges: int


def _walk_cache_path(pbf: Path) -> Path:
    st = pbf.stat()
    key = hashlib.sha256(f"{pbf.name}:{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()[:16]
    return get_settings().cache_dir / f"walk_graph_v{WALK_CACHE_VERSION}_{key}.npz"


def _build_walk_arrays(pbf: Path) -> dict[str, np.ndarray]:
    from pyrosm import OSM

    nodes, edges = OSM(str(pbf)).get_network(network_type="walking", nodes=True)
    ids = nodes["id"].to_numpy(dtype=np.int64)
    pos = {int(i): k for k, i in enumerate(ids)}
    u = np.array([pos.get(int(x), -1) for x in edges["u"].to_numpy()], dtype=np.int64)
    v = np.array([pos.get(int(x), -1) for x in edges["v"].to_numpy()], dtype=np.int64)
    length = edges["length"].to_numpy(dtype=float)
    ok = (u >= 0) & (v >= 0) & np.isfinite(length)
    u, v, length = u[ok], v[ok], length[ok]
    # keep the largest connected component, so every snapped stop can reach the others
    g = nx.Graph()
    g.add_edges_from(zip(u.tolist(), v.tolist()))
    comp = max(nx.connected_components(g), key=len)
    keep = np.array([a in comp and b in comp for a, b in zip(u.tolist(), v.tolist())])
    u, v, length = u[keep], v[keep], length[keep]
    used = np.unique(np.concatenate([u, v]))
    remap = -np.ones(len(ids), dtype=np.int64)
    remap[used] = np.arange(len(used))
    xy = project_lonlats(zip(nodes["lon"].to_numpy()[used], nodes["lat"].to_numpy()[used]))
    return {"u": remap[u], "v": remap[v], "length": length, "xy": xy}


_build_lock = threading.Lock()


@lru_cache(maxsize=1)
def walk_graph() -> WalkGraph | None:
    """The OSM pedestrian graph (largest component), cached as .npz in $DATA_DIR/cache."""
    with _build_lock:
        return _load_walk_graph()


def _load_walk_graph() -> WalkGraph | None:
    pbf = get_settings().data_dir / OSM_FILE
    if not pbf.is_file():
        return None
    cache = _walk_cache_path(pbf)
    try:
        if cache.is_file():
            arrays = dict(np.load(cache))
        else:
            arrays = _build_walk_arrays(pbf)
            tmp = cache.with_name(cache.stem + ".tmp.npz")
            np.savez_compressed(tmp, **arrays)
            tmp.replace(cache)
    except Exception:  # degrade to the straight-line estimate, never fail the request
        log.exception("walking graph unavailable")
        return None
    xy = arrays["xy"]
    adj: list[list[tuple[int, float]]] = [[] for _ in range(len(xy))]
    for a, b, w in zip(arrays["u"].tolist(), arrays["v"].tolist(), arrays["length"].tolist()):
        adj[a].append((b, w))
        adj[b].append((a, w))
    return WalkGraph(adj, xy, STRtree(shapely.points(xy)), len(arrays["u"]))


def _snap(xy: tuple[float, float]) -> tuple[int, float] | None:
    wg = walk_graph()
    if wg is None:
        return None
    idx = int(wg.tree.query_nearest(shapely.points(*xy))[0])
    return idx, float(math.hypot(wg.node_xy[idx, 0] - xy[0], wg.node_xy[idx, 1] - xy[1]))


def _settle(src: int, cutoff: float):
    """Dijkstra from a node: yields (node, metres) in increasing order, up to cutoff."""
    adj = walk_graph().adj
    dist = {src: 0.0}
    done = set()
    heap = [(0.0, src)]
    while heap:
        d, n = heapq.heappop(heap)
        if n in done:
            continue
        if d > cutoff:
            return
        done.add(n)
        yield n, d
        for m, w in adj[n]:
            nd = d + w
            if nd < dist.get(m, math.inf):
                dist[m] = nd
                heapq.heappush(heap, (nd, m))


@lru_cache(maxsize=1)
def _stop_index() -> dict[str, int]:
    return {s: i for i, s in enumerate(load_network().stop_ids)}


def _stop_xy(stop_id: str) -> tuple[float, float] | None:
    i = _stop_index().get(stop_id)
    if i is None:
        return None
    xy = load_network().stop_xy[i]
    return float(xy[0]), float(xy[1])


@lru_cache(maxsize=1)
def _stop_snaps() -> dict[str, tuple[int, float]]:
    out = {}
    for sid in load_network().stop_ids:
        sn = _snap(_stop_xy(sid))
        if sn is not None:
            out[sid] = sn
    return out


def walk_distance(a: str, b: str) -> tuple[float, bool]:
    """(metres, exact) between two stops. exact=False: straight line × 1.3 ("aproximativ")."""
    if a == b:
        return 0.0, True
    xa, xb = _stop_xy(a), _stop_xy(b)
    straight = math.hypot(xa[0] - xb[0], xa[1] - xb[1])
    sa, sb = _stop_snaps().get(a), _stop_snaps().get(b)
    if sa is not None and sb is not None:
        for node, d in _settle(sa[0], WALK_CUTOFF_M):
            if node == sb[0]:
                return sa[1] + d + sb[1], True
    return straight * APPROX_FACTOR, False


# --- nearest served stop ----------------------------------------------------------------


@dataclass
class NearestStats:
    total: int = 0
    approx: int = 0


SNAP_MARGIN_M = 100.0  # snapping offsets can reorder candidates by up to about this much


def _walk_to_candidates(stop_id: str, cands: dict[str, float], own_route_cands: set[str]) -> dict[str, tuple[float, bool]]:
    """Walking distance from a stop to the candidate stops, settled nearest first.

    Stops early once the nearest candidate (and the nearest one on the same
    route, if it can still win) is known; candidates the graph cannot reach
    get straight line × 1.3.
    """
    out: dict[str, tuple[float, bool]] = {}
    if stop_id in cands:
        out[stop_id] = (0.0, True)
    src = _stop_snaps().get(stop_id)
    snaps = _stop_snaps()
    by_node: dict[int, list[str]] = {}
    for sid in cands:
        if sid != stop_id and sid in snaps:
            by_node.setdefault(snaps[sid][0], []).append(sid)
    exhausted = True
    if src is not None and by_node:
        best_any = 0.0 if stop_id in cands else None
        best_same = 0.0 if stop_id in cands and stop_id in own_route_cands else None
        for node, d in _settle(src[0], WALK_CUTOFF_M):
            total = src[1] + d
            if best_any is not None and total > best_any + SNAP_MARGIN_M and (
                    best_same is not None or total > best_any + SAME_ROUTE_SLACK_M + SNAP_MARGIN_M):
                exhausted = False
                break
            for sid in by_node.get(node, ()):
                w = total + snaps[sid][1]
                out[sid] = (w, True)
                best_any = w if best_any is None else min(best_any, w)
                if sid in own_route_cands:
                    best_same = w if best_same is None else min(best_same, w)
    if exhausted:
        for sid, straight in cands.items():
            if sid not in out:
                out[sid] = (straight * APPROX_FACTOR, False)
    return out


def nearest_served(row: dict, svc: ServiceState, stats: NearestStats | None = None) -> dict | None:
    """Nearest stop with a remaining departure in the window, within 1,500 m (SPEC §6.1 item 9).

    Candidates: any stop within 1,500 m (straight line) that keeps a departure
    of any route in the window (the row's own stop counts if another line
    still serves it). The same route and direction wins when it is at most
    400 m farther on foot than the nearest one.
    """
    if svc.counts is None:
        return None
    n = load_network()
    stop_id, own = row["stopId"], (row["routeId"], int(row["directionId"]))
    xy = _stop_xy(stop_id)
    if xy is None:
        return None
    d = np.hypot(n.stop_xy[:, 0] - xy[0], n.stop_xy[:, 1] - xy[1])
    cands: dict[str, float] = {}
    keys_of: dict[str, set] = {}
    for i in np.nonzero(d <= NEAREST_MAX_M)[0]:
        sid = n.stop_ids[int(i)]
        keys = svc.served(sid, without=own if sid == stop_id else None)
        if keys:
            cands[sid] = float(d[i])
            keys_of[sid] = keys
    if not cands:
        return None
    same = {s for s in cands if own in keys_of[s]}
    walks = _walk_to_candidates(stop_id, cands, same)
    scored = sorted((w[0], w[1], sid) for sid, w in walks.items())
    best = scored[0]
    same_scored = [x for x in scored if x[2] in same]
    if same_scored and same_scored[0][0] <= best[0] + SAME_ROUTE_SLACK_M:
        best = same_scored[0]
    dist, exact, sid = best
    if stats is not None:
        stats.total += 1
        stats.approx += 0 if exact else 1
    s = n.stop_by_id[sid]
    return {"stopId": sid, "name": s["name"], "location": s["location"],
            "distanceMeters": round(dist), "routeIds": sorted({r for r, _ in keys_of[sid]})}


def walking_note(stats: NearestStats) -> str:
    base = "Distanța până la cea mai apropiată stație deservită: mers pe jos pe rețeaua pietonală OSM"
    if walk_graph() is None:
        return ("Distanța până la cea mai apropiată stație deservită: linie dreaptă × 1,3, aproximativ "
                "(graful OSM lipsește) / straight line × 1.3, approximate")
    if stats.approx:
        return (f"{base}; {stats.approx} din {stats.total} aproximative (linie dreaptă × 1,3) / "
                f"walking on OSM paths, {stats.approx} of {stats.total} approximate (straight line × 1.3)")
    return f"{base} / walking distance on OSM footpaths"


def osm_provenance(note: str) -> Provenance:
    p = prov.from_sources("osm")
    pbf = get_settings().data_dir / OSM_FILE
    if p is None:
        if not pbf.is_file():
            return prov.provenance("OpenStreetMap (lipsă / missing)", now(), None, None, note)
        p = prov.for_file("OpenStreetMap", pbf, "https://www.openstreetmap.org", None, None)
    return p.model_copy(update={"note": f"{note}. {p.note or ''}".strip(". ").strip()})


# --- population ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PopGrid:
    xy: np.ndarray            # (N, 2) metric cell centres, cells with residents > 0
    residents: np.ndarray     # (N,)
    zone: np.ndarray          # (N,) index into load_zones().slugs, -1 outside


@lru_cache(maxsize=1)
def pop_grid() -> PopGrid | None:
    with _build_lock:
        return _load_pop_grid()


def _load_pop_grid() -> PopGrid | None:
    path = get_settings().data_dir / POP_FILE
    if not path.is_file():
        return None
    import rasterio

    with rasterio.open(path) as r:
        a = r.read(1).astype(float)
        nodata = r.nodata
        rows, cols = np.nonzero(np.isfinite(a) & (a > 0) & ((a != nodata) if nodata is not None else True))
        xs, ys = rasterio.transform.xy(r.transform, rows, cols, offset="center")
    lon, lat = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    z = load_zones()
    zone = -np.ones(len(lon), dtype=np.int32)
    for i, shp in enumerate(z.shapes):
        inside = shapely.contains_xy(shp, lon, lat) & (zone < 0)
        zone[inside] = i
    return PopGrid(project_lonlats(zip(lon, lat)), a[rows, cols], zone)


def pop_provenance() -> Provenance:
    p = prov.from_sources("ghsl")
    if p is None:
        p = prov.for_file("GHSL population grid (JRC)", get_settings().data_dir / POP_FILE)
    return p.model_copy(update={"note": GHSL_LABEL})


def residents_losing(suspended: set[str], svc: ServiceState) -> dict[int, tuple[float, float | None]] | None:
    """{zone index (-1 outside): (residents, maxExtraWalkMeters)}; None if the raster is missing."""
    grid = pop_grid()
    if grid is None:
        return None
    if not suspended:
        return {}
    n = load_network()
    idx = _stop_index()
    susp_xy = n.stop_xy[[idx[s] for s in suspended if s in idx]]
    served_ids = [s for s in svc.remaining if svc.remaining[s] and s in idx]
    served_xy = n.stop_xy[[idx[s] for s in served_ids]] if served_ids else np.zeros((0, 2))
    # cells near any suspended stop (bounding box first, then exact distance)
    lo, hi = susp_xy.min(axis=0) - RESIDENT_RADIUS_M, susp_xy.max(axis=0) + RESIDENT_RADIUS_M
    box = np.all((grid.xy >= lo) & (grid.xy <= hi), axis=1)
    cand = np.nonzero(box)[0]
    if len(cand) == 0:
        return {}
    cxy = grid.xy[cand]
    d_susp = np.min(np.hypot(cxy[:, None, 0] - susp_xy[None, :, 0], cxy[:, None, 1] - susp_xy[None, :, 1]), axis=1)
    near = d_susp <= RESIDENT_RADIUS_M
    cand, cxy, d_susp = cand[near], cxy[near], d_susp[near]
    if len(cand) == 0:
        return {}
    if len(served_xy):
        d_served = np.min(np.hypot(cxy[:, None, 0] - served_xy[None, :, 0],
                                   cxy[:, None, 1] - served_xy[None, :, 1]), axis=1)
    else:
        d_served = np.full(len(cand), np.inf)
    losing = d_served > RESIDENT_RADIUS_M
    out: dict[int, tuple[float, float | None]] = {}
    for c, ds, dv in zip(cand[losing], d_susp[losing], d_served[losing]):
        zi = int(grid.zone[c])
        res, mx = out.get(zi, (0.0, None))
        extra = float(dv - ds) if np.isfinite(dv) else None
        if extra is not None:
            mx = extra if mx is None else max(mx, extra)
        out[zi] = (res + float(grid.residents[c]), mx)
    return out


# --- the Impact -----------------------------------------------------------------------------

METHOD = I18n(
    ro="Plecări pierdute: orarul GTFS al fiecărei linii și direcții, la fiecare stație afectată, în fereastra "
       "lucrării. Stație suspendată: nicio altă plecare a vreunei linii în fereastră. Locuitori fără stație: "
       "celule GHSL 2020 de 100 m (model, nu recensământ) aflate la cel mult 400 m (linie dreaptă) de o stație "
       "suspendată și fără nicio stație deservită la 400 m. Stațiile neclare contează doar după o decizie.",
    en="Departures lost: the GTFS timetable of each line and direction at each affected stop inside the "
       "closure window. Suspended stop: no other departure of any line in the window. Residents losing their "
       "stop: GHSL 2020 100 m cells (a model, not a census) within 400 m (straight line) of a suspended stop "
       "with no served stop within 400 m. Unsure stops count only after a decision.",
)


def _closure_and_analysis(closure_id: str) -> tuple[dict, dict]:
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


def build_impact(closure: dict, rows: list[dict]) -> Impact:
    """Impact from a closure and its analysis rows (decisions applied). Pure apart from caches."""
    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    tt = timetable_for(start)
    cw = count_window(start, end, tt)
    counts = departure_counts(cw, tt)
    if counts is None:
        raise invalid(cw.note or "Window outside the GTFS feed.", code="OUTSIDE_FEED")
    lost_rows = [r for r in rows if counts_as_lost(r)]
    lost = {row_key(r) for r in lost_rows}
    svc = ServiceState.build(counts, lost)
    suspended = svc.suspended_stops()

    z = load_zones()
    zone_of_stop = {r["stopId"]: r.get("zoneSlug") or zone_for_point(*r["location"]) for r in lost_rows}
    by_zone: dict[str, dict] = {}

    def zrow(slug: str | None) -> dict:
        slug = slug or OUTSIDE_SLUG
        if slug not in by_zone:
            by_zone[slug] = {"slug": slug, "name": z.names.get(slug, OUTSIDE_NAME), "stopsSuspended": 0,
                             "departuresLost": 0, "residentsLosingStop": None, "maxExtraWalkMeters": None}
        return by_zone[slug]

    dep_total = 0
    for k in lost:
        n_dep = counts.get(k, 0)
        dep_total += n_dep
        zrow(zone_of_stop.get(k[0]))["departuresLost"] += n_dep
    for s in suspended:
        zrow(zone_of_stop.get(s))["stopsSuspended"] += 1

    res = residents_losing(suspended, svc)
    total_res = None
    if res is not None:
        total_res = 0.0
        for row in by_zone.values():
            row["residentsLosingStop"] = 0
        for zi, (people, mx) in res.items():
            row = zrow(z.slugs[zi] if zi >= 0 else None)
            row["residentsLosingStop"] = int(round((row["residentsLosingStop"] or 0) + people))
            if mx is not None:
                cur = row["maxExtraWalkMeters"]
                row["maxExtraWalkMeters"] = round(mx) if cur is None else max(cur, round(mx))
            total_res += people
        for row in by_zone.values():
            if row["residentsLosingStop"] is None:
                row["residentsLosingStop"] = 0
        total_res = int(round(total_res))

    zones = sorted(by_zone.values(), key=lambda r: (r["slug"] == OUTSIDE_SLUG, -r["departuresLost"],
                                                    -r["stopsSuspended"], r["name"]))
    provenance = [timetable_provenance(tt, cw), load_network().provenance, z.provenance]
    if res is not None:
        provenance.append(pop_provenance())
    else:
        provenance.append(prov.provenance("GHSL population grid (JRC)", now(), None, None,
                                          "Lipsește rasterul GHSL: locuitori necunoscuți / raster missing"))
    return Impact(
        closureId=closure["id"],
        window=Window(**closure["window"]),
        totals=ImpactTotals(
            stopsSuspended=len(suspended),
            departuresLost=dep_total,
            routesAffected=len({k[1] for k in lost}),
            residentsLosingStop=total_res,
            stopRoutePairsLost=len(lost),
        ),
        byZone=[ZoneImpact(**r) for r in zones],
        method=METHOD,
        provenance=provenance,
    )


_memo: dict[str, tuple[str, Impact]] = {}


def compute_impact(closure_id: str) -> Impact:
    """Impact of a stored, analyzed closure. Stored as state part "impact"."""
    closure, analysis = _closure_and_analysis(closure_id)
    sig = hashlib.sha256(json.dumps([closure["window"], [(row_key(r), r["state"], r.get("confirmed"))
                                                        for r in analysis["stops"]]],
                                    sort_keys=True).encode()).hexdigest()
    hit = _memo.get(closure_id)
    if hit and hit[0] == sig and state.exists("closures", closure_id, state.PART_IMPACT):
        return hit[1]
    impact = build_impact(closure, analysis["stops"])
    state.write("closures", closure_id, impact, part=state.PART_IMPACT)
    _memo[closure_id] = (sig, impact)
    return impact


def warm() -> None:
    """Load the caches a live request needs (GTFS index, walking graph, GHSL grid)."""
    try:
        gtfs.departure_index()
        gtfs.stop_patterns()
        walk_graph()
        _stop_snaps()
        pop_grid()
        for c in state.list_all("closures"):  # older timetables the stored closures need (Mocioni: 4.29)
            timetable_for((c.get("window") or {}).get("start"))
    except Exception:  # a missing source shows up in the request, not here
        log.exception("warm-up failed")


def warm_in_background() -> threading.Thread:
    t = threading.Thread(target=warm, name="m1-warm", daemon=True)
    t.start()
    return t
