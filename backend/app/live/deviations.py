"""R18: off-route runs in our live recording, and whether a notice explains them.

Each fresh vehicle position (healthy snapshot, position at most MAX_REPORT_AGE_SEC old,
one per vehicle and updatedAt) is measured against every GTFS shape of its line (UTM
34N): the feed often tags a vehicle with another trip of its line. A run is >=
MIN_REPORTS consecutive positions of one vehicle on one trip more than OFF_ROUTE_M from
all of them. Ignored: runs followed by a GPS loss (no fresh position of the vehicle for
GPS_LOSS: the positions just before it are the onboard unit's extrapolation; tram 7 at
Piața Sfânta Maria on 14 Nov ran on straight along 16 Decembrie on screen, then
reappeared on its own route; every tram shape lies within 5 m of the OSM tram rails,
so it was not a wrong shape); runs whose middle is outside the reported trip's time (BEFORE_TRIP /
AFTER_TRIP: positioning, a wrong trip id); a vehicle standing (>= STANDING_MIN under
STANDING_MPS: layover); runs around either end of the trip's shape, leaving its last
stop or reaching its first (turning loops; trams run on 90-350 m past the last stop to
their loop); runs near a garage stop. The rest are grouped by line, direction and the named OSM street the
positions are nearest to, then classified:

- „anuntata”: a published closure active at that time acts on the line and lies within
  CLOSURE_M of the run, or a saved STPT
  notice names both the line and that street and the run falls in a window the notice
  states (no window stated: within NOTICE_DAYS after it was posted);
- „fara_anunt”: „abatere de la traseu fără anunț găsit de noi — de verificat”, for a
  person to confirm (as in R4).

Nothing is fetched; distances come from the City Hall's live data, recorded by us.
"""

from __future__ import annotations

import io
import logging
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from functools import lru_cache

log = logging.getLogger("reteaua_vie.live.deviations")

import numpy as np
import pandas as pd
import shapely

from app.common import gtfs, state, stpt_posts, vehicles
from app.common import provenance as prov
from app.common.geo import project_lonlats
from app.common.timeutil import gtfs_service_start, iso, parse_iso
from app.config import TZ, real_now
from app.live import missing

OFF_ROUTE_M = 80
MIN_REPORTS = 3
TERMINAL_M = 250
DEPOT_M = 300
MAX_REPORT_AGE_SEC = 120
BEFORE_TRIP = timedelta(minutes=20)   # a run this long before the trip's first departure is positioning
AFTER_TRIP = timedelta(minutes=60)    # ... or this long after its last one (a late vehicle keeps its trip id)
STANDING_MIN = timedelta(minutes=5)   # a run this long at under STANDING_MPS is a vehicle standing (layover)
STANDING_MPS = 1.0
GPS_LOSS = timedelta(minutes=5)       # no fresh position of the vehicle this long after a run: signal lost
NOTICE_DAYS = 60
CLOSURE_M = 2000   # a closure explains a run only this close to its geometry (a detour stays near the works)
LABEL_FARA = {"ro": "abatere de la traseu fără anunț găsit de noi — de verificat",
              "en": "off route, no notice found by us — to be checked"}


# --- shapes, stops, streets (cached per feed / once) ---------------------------------------

_SHAPES: dict[str, dict[str, shapely.LineString]] = {}


def _shapes(f: gtfs.Feed) -> dict[str, shapely.LineString]:
    """shape_id -> LineString in UTM metres."""
    if f.sha256 not in _SHAPES:
        with zipfile.ZipFile(f.path) as z:
            sh = pd.read_csv(io.BytesIO(z.read("shapes.txt")), dtype={"shape_id": str})
        out = {}
        for sid, g in sh.sort_values(["shape_id", "shape_pt_sequence"]).groupby("shape_id"):
            xy = project_lonlats(zip(g.shape_pt_lon.astype(float), g.shape_pt_lat.astype(float)))
            if len(xy) >= 2:
                out[str(sid)] = shapely.LineString(xy)
        _SHAPES[f.sha256] = out
    return _SHAPES[f.sha256]


_STOPS: dict[str, tuple] = {}


def _stops(f: gtfs.Feed):
    """(STRtree of stop points, stop names, garage points) in UTM."""
    if f.sha256 not in _STOPS:
        from app.m1_disruption.parser import fold

        s = f.stops
        xy = project_lonlats(zip(s.stop_lon.astype(float), s.stop_lat.astype(float)))
        pts = shapely.points(xy[:, 0], xy[:, 1])
        names = s.stop_name.tolist()
        garages = [p for p, n in zip(pts, names) if any(k in fold(n) for k in ("garaj", "depou"))]
        _STOPS[f.sha256] = (shapely.STRtree(pts), names, garages)
    return _STOPS[f.sha256]


@lru_cache(maxsize=1)
def _streets():
    """(STRtree of named OSM street edges in UTM, their normalised names, display names by key)."""
    from app.m1_disruption import parser

    o = parser.osm_streets()
    segs, names = [], []
    for name, coords in zip(o.names, o.coords):
        if name and len(coords) >= 2:
            segs.append(shapely.LineString(project_lonlats(map(tuple, coords))))
            names.append(name)
    _, by_key, _ = parser.register()
    return shapely.STRtree(segs), names, {k: s.name for k, s in by_key.items()}


# --- the recording -------------------------------------------------------------------------

def reports(start: datetime, end: datetime) -> tuple[pd.DataFrame, list[str], float]:
    """Fresh positions in [start, end): one per (vehicle, updatedAt), from healthy snapshots;
    plus the files read and the healthy share of the window's minutes."""
    rows, seen, healthy_min, files = [], set(), set(), []
    s_ts, e_ts = start.timestamp(), end.timestamp()
    for path, hour in vehicles.recording_files():
        if hour.timestamp() + 3600 <= s_ts or hour.timestamp() >= e_ts:
            continue
        files.append(path.name)
        for snap in vehicles.read_file(path):
            t = parse_iso(snap["fetchedAt"]).timestamp()
            age = snap.get("realtimeAgeSec")
            if not (s_ts <= t < e_ts) or not isinstance(age, (int, float)) or age > missing.HEALTHY_AGE_SEC:
                continue
            healthy_min.add(int((t - s_ts) // 60))
            for v in snap.get("vehicles") or []:
                upd, trip = v.get("updatedAt"), v.get("tripId")
                if v.get("lat") is None or not isinstance(upd, (int, float)) or not trip:
                    continue
                if t - upd > MAX_REPORT_AGE_SEC or (v.get("id"), upd) in seen:
                    continue
                seen.add((v.get("id"), upd))
                rows.append((float(upd), str(v.get("id")), trip, v.get("routeId"), v.get("directionId"),
                             float(v["lon"]), float(v["lat"])))
    df = pd.DataFrame(rows, columns=["t", "vid", "trip", "route", "dir", "lon", "lat"])
    if len(df):
        xy = project_lonlats(zip(df.lon, df.lat))
        df["x"], df["y"] = xy[:, 0], xy[:, 1]
    minutes = max(1, int(-(-(e_ts - s_ts) // 60)))
    return df.sort_values(["vid", "trip", "t"]).reset_index(drop=True), files, round(len(healthy_min) / minutes, 4)


_ROUTE_PATHS: dict[str, dict[str, object]] = {}


def _route_paths(f: gtfs.Feed) -> dict[str, object]:
    """route_id -> every GTFS shape of the line (all directions and variants), merged."""
    if f.sha256 not in _ROUTE_PATHS:
        shapes = _shapes(f)
        pairs = f.trips[["route_id", "shape_id"]].drop_duplicates()
        out = {}
        for rid, g in pairs.groupby("route_id"):
            lines = [shapes[str(s)] for s in g.shape_id if str(s) in shapes]
            if lines:
                out[rid] = shapely.union_all(lines)
        _ROUTE_PATHS[f.sha256] = out
    return _ROUTE_PATHS[f.sha256]


def find_runs(df: pd.DataFrame, f: gtfs.Feed) -> list[dict]:
    """Runs of >= MIN_REPORTS consecutive positions > OFF_ROUTE_M from every GTFS shape of the line.

    Every shape of the line, not only the reported trip's: the City Hall feed often tags a
    vehicle with another trip of its line (other direction or variant, hours from its time)."""
    if df.empty:
        return []
    paths = _route_paths(f)
    shape_of = f.trips.set_index("trip_id").shape_id
    df = df.assign(shape=df.trip.map(shape_of))
    dist = np.full(len(df), np.nan)
    for rid, idx in df.groupby("route").indices.items():
        path = paths.get(rid)
        if path is not None:
            dist[idx] = shapely.distance(shapely.points(df.x.to_numpy()[idx], df.y.to_numpy()[idx]), path)
    df = df.assign(d=dist)
    runs = []
    for (vid, trip), g in df.groupby(["vid", "trip"], sort=False):
        off = (g.d > OFF_ROUTE_M).to_numpy()
        i, n = 0, len(g)
        while i < n:
            if not off[i]:
                i += 1
                continue
            j = i
            while j < n and off[j]:
                j += 1
            if j - i >= MIN_REPORTS:
                part = g.iloc[i:j]
                runs.append({"vid": vid, "trip": trip, "route": part.route.iloc[0], "dir": part.dir.iloc[0],
                             "shape": str(part["shape"].iloc[0]), "part": part})
            i = j
    return runs


# --- classification -----------------------------------------------------------------------

def _published_actions(at: datetime) -> dict[str, tuple[str, object]]:
    """route_id -> (closure id, its geometry in UTM or None), for published closures active at `at`
    that act on the route."""
    from shapely.geometry import shape

    from app.common.geo import to_metric

    out = {}
    for c in state.list_all("closures"):
        if c.get("status") != "published" or not c.get("window"):
            continue
        if parse_iso(c["window"]["start"]) <= at < parse_iso(c["window"]["end"]):
            geom = to_metric(shape(c["geometry"])) if c.get("geometry") else None
            for a in c.get("routeActions") or []:
                out.setdefault(a.get("routeId"), (c["id"], geom))
    return out


@lru_cache(maxsize=1)
def _notice_index(signature: tuple) -> list[tuple]:
    """[(post, route ids it names, street keys it names, windows it states)] for every saved STPT post."""
    from app.m1_disruption import parser

    out = []
    for p in stpt_posts.load_posts().values():
        routes, streets, windows = set(), set(), []
        for sentence in parser.split_sentences(p.title + ". " + p.text):
            w = parser.window_from(sentence, p.date)
            if w is not None:
                windows.append((w.start, w.end, w.open_end))
            for tok in parser.line_tokens(sentence):
                rid = parser._route_for(tok)
                if rid:
                    routes.add(rid)
            for _, st in parser.streets_in(sentence):
                streets.update(st.keys)
        out.append((p, frozenset(routes), frozenset(streets), tuple(windows)))
    return out


def _notice_for(route_id: str, street_key: str | None, at: datetime):
    if not street_key:
        return None
    sig = tuple(sorted((i, p.modified.isoformat()) for i, p in stpt_posts.load_posts().items()))
    for p, routes, streets, windows in _notice_index(sig):
        if route_id not in routes or street_key not in streets:
            continue
        if windows:
            # closed windows first: an open end („începând cu …”) from another sentence of the same notice
            # (10862: the vaporetto, 19 Sep) must not stretch the notice to 31 Dec
            closed = [(a, b) for a, b, open_end in windows if not open_end]
            if any(a <= at <= b for a, b in (closed or [(a, b) for a, b, _ in windows])):
                return p
        elif p.date <= at <= p.date + timedelta(days=NOTICE_DAYS):
            return p
    return None


def _ts(x: float) -> str:
    return iso(datetime.fromtimestamp(x, tz=timezone.utc))


def detect(start: datetime, end: datetime) -> dict:
    """Deviations for [start, end) (app/models/live_deviations.py)."""
    start, end = start.astimezone(TZ), end.astimezone(TZ)
    df, files, share = reports(start, end)
    f = gtfs.feed(start)
    runs = find_runs(df, f)
    shapes = _shapes(f)
    stop_tree, stop_names, garages = _stops(f)
    garage_union = shapely.union_all(garages) if garages else None
    counts = Counter()
    kept = []
    spans = missing._trip_table(f).set_index("trip_id")[["first_sec", "last_sec"]]
    times_of = {vid: np.sort(g.t.to_numpy()) for vid, g in df.groupby("vid")} if len(df) else {}
    e_ts = end.timestamp()
    for r in runs:
        part, line = r["part"], shapes[r["shape"]]
        mid = shapely.Point(float(part.x.mean()), float(part.y.mean()))
        counts["runs"] += 1
        # positions just before a GPS loss are extrapolated by the onboard unit (tram 7 at Piața Sfânta
        # Maria, 14 Nov: straight on along 16 Decembrie, frozen ~10 min, then back on its own route)
        last_t = float(part.t.iloc[-1])
        ts = times_of.get(r["vid"])
        nxt = ts[np.searchsorted(ts, last_t, side="right")] if ts is not None and (ts > last_t).any() else None
        if (nxt is not None and nxt - last_t >= GPS_LOSS.total_seconds()) or (
                nxt is None and e_ts - last_t >= GPS_LOSS.total_seconds()):
            counts["ignoredGpsLoss"] += 1
            continue
        if r["trip"] in spans.index:
            t0 = datetime.fromtimestamp(float(part.t.iloc[0]), tz=timezone.utc).astimezone(TZ)
            t1 = datetime.fromtimestamp(float(part.t.iloc[-1]), tz=timezone.utc).astimezone(TZ)
            first, last = spans.loc[r["trip"]]
            t_mid = t0 + (t1 - t0) / 2
            on_trip = False
            for day in (t0.date() - timedelta(days=1), t0.date()):
                a = gtfs_service_start(day) + timedelta(seconds=int(first))
                b = gtfs_service_start(day) + timedelta(seconds=int(last))
                if a - BEFORE_TRIP <= t_mid <= b + AFTER_TRIP:
                    on_trip = True
            if not on_trip:
                counts["ignoredOffSchedule"] += 1
                continue
            xy = np.column_stack([part.x.to_numpy(), part.y.to_numpy()])
            path_m = float(np.hypot(*np.diff(xy, axis=0).T).sum()) if len(xy) > 1 else 0.0
            if t1 - t0 >= STANDING_MIN and path_m / max(1.0, (t1 - t0).total_seconds()) < STANDING_MPS:
                counts["ignoredStanding"] += 1
                continue
        ends = (shapely.Point(line.coords[0]), shapely.Point(line.coords[-1]))
        p0 = shapely.Point(float(part.x.iloc[0]), float(part.y.iloc[0]))
        p1 = shapely.Point(float(part.x.iloc[-1]), float(part.y.iloc[-1]))
        if (min(mid.distance(e) for e in ends) <= TERMINAL_M or p0.distance(ends[1]) <= TERMINAL_M
                or p1.distance(ends[0]) <= TERMINAL_M):  # around a terminal, or leaving the last stop / reaching the first
            counts["ignoredTerminal"] += 1
            continue
        if garage_union is not None and mid.distance(garage_union) <= DEPOT_M:
            counts["ignoredDepot"] += 1
            continue
        kept.append((r, mid))

    info = missing._route_info(f)
    tree, street_names, display = _streets() if kept else (None, [], {})
    seen_trips = (df.assign(dk=pd.to_numeric(df.dir, errors="coerce").fillna(-1).astype(int))
                  .groupby(["route", "dk"]).trip.nunique().to_dict()) if len(df) else {}
    groups: dict[tuple, dict] = {}
    for r, mid in kept:
        part, line = r["part"], shapes[r["shape"]]
        pts = shapely.points(part.x.to_numpy(), part.y.to_numpy())
        keys = [street_names[i] for i in tree.nearest(pts)]
        street_key = Counter(keys).most_common(1)[0][0] if keys else None
        xy = np.column_stack([part.x.to_numpy(), part.y.to_numpy()])
        path_m = float(np.hypot(*np.diff(xy, axis=0).T).sum()) if len(xy) > 1 else 0.0
        along = abs(line.project(pts[-1]) - line.project(pts[0]))
        track = {
            "tripId": r["trip"], "vehicleId": r["vid"],
            "start": _ts(float(part.t.iloc[0])), "end": _ts(float(part.t.iloc[-1])),
            "reports": int(len(part)), "maxDistanceM": int(part.d.max()),
            "extraKm": round(max(0.0, path_m - along) / 1000, 2),
            "coordinates": [[round(lo, 6), round(la, 6)] for lo, la in zip(part.lon, part.lat)],
        }
        key = (r["route"], r["dir"], street_key)
        g = groups.get(key)
        if g is None:
            meta = info.get(r["route"], {})
            g = groups[key] = {
                "routeId": r["route"], "shortName": meta.get("shortName"), "mode": meta.get("mode"),
                "directionId": int(r["dir"]) if r["dir"] in (0, 1) else None,
                "street": display.get(street_key) or (street_key.title() if street_key else None),
                "nearStop": stop_names[int(stop_tree.nearest(mid))], "_street_key": street_key, "tracks": [],
            }
        g["tracks"].append(track)

    out_groups = []
    for g in groups.values():
        tracks = sorted(g.pop("tracks"), key=lambda t: t["start"])
        street_key = g.pop("_street_key")
        first_at = parse_iso(tracks[0]["start"])
        closure = None
        hit = _published_actions(first_at).get(g["routeId"])
        if hit is not None:
            cid, geom = hit
            xy = project_lonlats(map(tuple, tracks[0]["coordinates"]))
            where = shapely.Point(float(xy[:, 0].mean()), float(xy[:, 1].mean()))
            if geom is None or where.distance(geom) <= CLOSURE_M:
                closure = cid
        post = None if closure else _notice_for(g["routeId"], street_key, first_at)
        if closure or post:
            cls = "anuntata"
            label = {"ro": f"abatere anunțată ({'lucrare publicată ' + closure if closure else f'anunț STPT {post.id}'})",
                     "en": "announced diversion"}
        else:
            cls, label = "fara_anunt", LABEL_FARA
        trips = len({t["tripId"] for t in tracks})
        seen = int(seen_trips.get((g["routeId"], g["directionId"]), 0))
        out_groups.append({
            **g, "classification": cls, "label": label, "closureId": closure,
            "notice": {"postId": post.id, "url": post.link, "title": post.title} if post else None,
            "runs": len(tracks), "trips": trips, "tripsSeen": seen, "share": round(trips / seen, 4) if seen else None,
            "firstAt": tracks[0]["start"], "lastAt": max(t["end"] for t in tracks),
            "maxDistanceM": max(t["maxDistanceM"] for t in tracks),
            "extraKm": round(sum(t["extraKm"] for t in tracks), 2), "tracks": tracks,
        })
    if out_groups:  # R25: measured extra delay per group, from L0 only (Fri afternoon + weekend; no weekday fill-in)
        try:
            from app.live.delay_effect import run_effects
            from app.observed import store

            ev, seg = store.events(), store.segments()
        except Exception:
            log.exception("R25 delay effect failed; groups without a measured delay")
            ev = seg = None
        if ev is not None:
            for g in out_groups:
                try:
                    g["delayEffect"] = run_effects(g["tracks"], ev, seg)
                except Exception:
                    log.exception("R25 delay effect failed for %s", g.get("routeId"))
                    g["delayEffect"] = None
    out_groups.sort(key=lambda g: (g["classification"] != "fara_anunt", -g["runs"], g["shortName"] or ""))
    counts["kept"] = len(kept)
    counts["announced"] = sum(g["runs"] for g in out_groups if g["classification"] == "anuntata")
    counts["unannounced"] = counts["kept"] - counts["announced"]

    status = "ok" if share >= missing.MIN_HEALTHY_SHARE else "inregistrare_incompleta"
    provenance = [
        f.provenance.model_dump(),
        prov.vehicles_provenance(real_now() if df.empty else datetime.fromtimestamp(float(df.t.max()), tz=timezone.utc),
                                 f"Fereastra / window {iso(start)} – {iso(end)}; {len(df)} poziții proaspete / fresh "
                                 f"positions; {share:.0%} din minute acoperite; fișiere / files: "
                                 f"{', '.join(files) or 'niciunul / none'}").model_dump(),
        prov.provenance("Rețeaua Vie R18, abateri de la traseu / off-route detector", real_now(), None, None,
                        f"≥ {MIN_REPORTS} poziții consecutive la > {OFF_ROUTE_M} m de orice traseu GTFS al liniei; ignorate: "
                        f"urmate de pierderea semnalului GPS (nicio poziție nouă ≥ {int(GPS_LOSS.total_seconds() // 60)} min: "
                        f"pozițiile de dinainte sunt extrapolate), "
                        f"în afara orei cursei (cu {int(BEFORE_TRIP.total_seconds() // 60)} min înainte, "
                        f"{int(AFTER_TRIP.total_seconds() // 60)} min după), vehicul staționat (≥ "
                        f"{int(STANDING_MIN.total_seconds() // 60)} min sub {STANDING_MPS:g} m/s), ≤ {TERMINAL_M} m de "
                        f"capetele traseului (bucle, plecare spre buclă), ≤ {DEPOT_M} m de un garaj. Străzi: OpenStreetMap. "
                        f"„Anunțată” = lucrare publicată în platformă sau anunț STPT care numește linia și strada. "
                        f"Deducem din datele live; nu e o constatare a STPT.").model_dump(),
    ]
    if any(g["notice"] for g in out_groups):
        seen_posts = set()
        for g in out_groups:
            n = g["notice"]
            if n and n["postId"] not in seen_posts:
                seen_posts.add(n["postId"])
                p = stpt_posts.get_post(n["postId"])
                if p:
                    provenance.append(p.provenance().model_dump())
    return {
        "window": {"start": iso(start), "end": iso(end)},
        "status": status,
        "thresholds": {"offRouteMeters": OFF_ROUTE_M, "minReports": MIN_REPORTS, "terminalMeters": TERMINAL_M,
                       "depotMeters": DEPOT_M, "maxReportAgeSec": MAX_REPORT_AGE_SEC,
                       "beforeTripMinutes": int(BEFORE_TRIP.total_seconds() // 60),
                       "afterTripMinutes": int(AFTER_TRIP.total_seconds() // 60),
                       "standingMinutes": int(STANDING_MIN.total_seconds() // 60),
                       "standingMetresPerSecond": STANDING_MPS,
                       "gpsLossMinutes": int(GPS_LOSS.total_seconds() // 60)},
        "reports": int(len(df)),
        "counts": {k: int(counts.get(k, 0)) for k in
                   ("runs", "ignoredGpsLoss", "ignoredOffSchedule", "ignoredStanding", "ignoredTerminal", "ignoredDepot", "kept", "announced",
                    "unannounced")},
        "groups": out_groups,
        "provenance": provenance,
    }
