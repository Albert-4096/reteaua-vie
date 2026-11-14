"""A11: transfers at hubs, timetable vs. recording (GET /api/transfers).

A hub is the set of stops with the same name before „(” (e.g. „Piața Iuliu Maniu (Calea Șagului)” and
„Piața Iuliu Maniu (16 Decembrie 1989)”) within HUB_M of each other, served by at least MIN_ROUTES lines.

A connection: a recorded arrival of line A at a hub stop X (L0: arrival, or the passing time), and, for
each other line and direction B with a stop Y in the hub, the timetable's first departure of B at Y that
a rider arriving on time could reach (walk |XY| at WALK_KMH + BUFFER_SEC) and that leaves within
MAX_WAIT_SEC. Planned wait = that departure − A's planned arrival. Real wait = the first recorded B
departure the rider really reached (walking from A's real arrival) − A's real arrival. „Pierdută”: the
planned departure left (in the recording) before the rider reached it. A connection is counted only when
every B departure planned from 20 min before to 40 min after A's planned arrival was recorded (else we
cannot know which bus the rider got). One arriving trip = one bootstrap block.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict
from datetime import date

import numpy as np
import pandas as pd

from app.common import gtfs
from app.common import provenance as prov
from app.common.jobs import respond
from app.models.base import I18n
from app.observed import detour_cost as dc
from app.observed import store
from app.observed.build import _timetable as timetable_day
from app.observed.models import Estimate, TransferHub, TransferPair, TransferReport

log = logging.getLogger("reteaua_vie.observed")

ALGO_VERSION = 1
HUB_M = 400.0
MIN_ROUTES = 3
WALK_KMH = 4.8
BUFFER_SEC = 60.0
MAX_WAIT_SEC = 600.0
BEFORE_SEC, AFTER_SEC = 1200.0, 2400.0
TOP_HUBS = 15
TOP_PAIRS = 3
BOOT = 300
SEED = 20261116

METHOD = I18n(
    ro=("Nod = stațiile cu același nume (înainte de „(”) la cel mult 400 m, deservite de cel puțin 3 linii. "
        "Corespondență = o sosire înregistrată a unei linii și prima plecare din orar a altei linii din nod pe care "
        f"călătorul o prinde (mers pe jos {WALK_KMH:.1f} km/h + {BUFFER_SEC:.0f} s) și care pleacă în cel mult 10 min. "
        "Pierdută = în înregistrare, acea plecare a plecat înainte ca el s-o poată prinde. Așteptarea reală = până la "
        "prima plecare înregistrată pe care o prinde. Numărăm doar corespondențele pentru care toate plecările liniei "
        "a doua din jurul orei au fost înregistrate. Mediane și ponderi cu interval bootstrap 90 %, o cursă care "
        f"sosește = un bloc; sub {dc.MIN_TRIPS} curse: „neconcludent”. Doar vineri după-amiază și weekend.").replace(
        "4.8", "4,8"),
    en=("Hub = stops with the same name (before „(”) within 400 m, served by at least 3 lines. Connection = a "
        "recorded arrival of one line and the timetable's first departure of another hub line the rider can reach "
        f"(walking {WALK_KMH:.1f} km/h + {BUFFER_SEC:.0f} s) leaving within 10 min. Missed = in the recording that "
        "departure left before the rider could reach it. Real wait = until the first recorded departure the rider "
        "reaches. Only connections whose second line's departures around that time were all recorded count. Medians "
        f"and shares with a 90 % bootstrap interval, one arriving trip = one block; under {dc.MIN_TRIPS} trips: "
        "inconclusive. Friday afternoon and weekend only."),
)


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def hub_root(name: str) -> str:
    return name.split("(")[0].strip()


def find_hubs(stop_names: dict[str, str], stop_xy: dict[str, tuple[float, float]],
              stop_routes: dict[str, set[str]]) -> dict[str, list[str]]:
    """{hub name: stop ids}: same root name, within HUB_M of the group's first stop, >= MIN_ROUTES lines."""
    by_root: dict[str, list[str]] = defaultdict(list)
    for sid, name in stop_names.items():
        if sid in stop_routes and sid in stop_xy:
            by_root[hub_root(name)].append(sid)
    out = {}
    for root, sids in by_root.items():
        sids = sorted(sids, key=lambda s: -len(stop_routes[s]))
        x0, y0 = stop_xy[sids[0]]
        group = [s for s in sids if np.hypot(stop_xy[s][0] - x0, stop_xy[s][1] - y0) <= HUB_M]
        if len(set().union(*(stop_routes[s] for s in group))) >= MIN_ROUTES:
            out[root] = sorted(group)
    return out


def connections(arr: pd.DataFrame, dep: pd.DataFrame, walk: dict[tuple[str, str], float]) -> pd.DataFrame:
    """One row per measurable connection: from route, to (route, dir), planned and real wait, missed, block.

    arr: trip_id, service_date, route_id, stop_id, t (real arrival), s (planned arrival)
    dep: trip_id, service_date, route_id, direction_id, stop_id, p (planned departure), o (recorded, NaN = not)
    """
    rows = []
    for (sd, route_b, dir_b), g in dep.groupby(["service_date", "route_id", "direction_id"]):
        g = g.sort_values("p")
        p, o, ys = g["p"].to_numpy(float), g["o"].to_numpy(float), g["stop_id"].to_numpy()
        a = arr[(arr["service_date"] == sd) & (arr["route_id"] != route_b)]
        for t_a, s_a, x, route_a, tid, sdate in zip(a["t"], a["s"], a["stop_id"], a["route_id"], a["trip_id"],
                                                     a["service_date"]):
            w = np.array([walk.get((x, y), np.nan) for y in ys])
            reach_p = p >= s_a + w
            planned = np.where(reach_p & (p - s_a <= MAX_WAIT_SEC))[0]
            if not len(planned):
                continue
            j = planned[np.argmin(p[planned])]
            window = (p >= s_a - BEFORE_SEC) & (p <= s_a + AFTER_SEC)
            if np.isnan(o[window]).any():
                continue                                  # a B departure around then was not recorded
            reach_o = window & (o >= t_a + w)
            if not reach_o.any():
                continue
            real = float(np.min(o[reach_o]))
            rows.append((route_a, route_b, int(dir_b), float(p[j] - s_a), real - float(t_a),
                         bool(o[j] < t_a + w[j]), f"{tid}|{sdate}"))
    return pd.DataFrame(rows, columns=["from_route", "to_route", "to_dir", "planned", "real", "missed", "block"])


def _boot_stats(c: pd.DataFrame, rng: np.random.Generator) -> tuple[Estimate, Estimate, Estimate, Estimate]:
    """(missed share, planned wait, real wait, extra wait), blocks = arriving trips."""
    codes, uniq = pd.factorize(c["block"])
    n = len(uniq)
    if n == 0:
        e = dc._estimate(float("nan"), np.zeros(0), 0)
        return e, e, e, e
    missed = c["missed"].to_numpy(float)
    planned, real = c["planned"].to_numpy(float), c["real"].to_numpy(float)
    extra = real - planned
    w = rng.poisson(1.0, size=(BOOT, n))[:, codes]
    def share(x, ww):
        return float((x * ww).sum() / ww.sum()) if ww.sum() else float("nan")

    def med(x, ww):
        order = np.argsort(x, kind="stable")
        return dc._wmedian_sorted(x[order], ww[order]) if ww.sum() >= dc.MIN_OBS else float("nan")
    out = []
    for x, f in ((missed, share), (planned, med), (real, med), (extra, med)):
        point = f(x, np.ones(len(x), dtype=int))
        boots = np.array([f(x, w[b]) for b in range(BOOT)])
        if f is share:   # a share (0..1), not seconds: 3 decimals
            b_ = boots[~np.isnan(boots)]
            lo_, hi_ = np.percentile(b_, [5, 95]) if len(b_) else (np.nan, np.nan)
            r3 = lambda v: None if np.isnan(v) else round(float(v), 3)  # noqa: E731
            out.append(Estimate(sec=r3(point), low=r3(lo_), high=r3(hi_), n=n, conclusive=n >= dc.MIN_TRIPS))
        else:
            out.append(dc._estimate(point, boots, n))
    return tuple(out)


def compute(hub: str | None = None) -> TransferReport:
    rng = np.random.default_rng(SEED)
    cov = store.coverage()
    walk_info = {"speedKmh": WALK_KMH, "bufferSec": BUFFER_SEC, "maxMeters": HUB_M}
    if cov is None:
        return TransferReport(status="fara_inregistrare", label=None, walk=walk_info, hubs=[], method=METHOD,
                              provenance=[])
    ev = store.events()
    days = sorted({date.fromisoformat(d) for d in ev["service_date"].unique()})
    tt_ = timetable_day(days[-1])
    feed = gtfs._FEEDS[tt_.sha]
    short = dict(zip(feed.routes["route_id"], feed.routes.get("route_short_name", feed.routes["route_id"])))
    lonlat = {str(s): (float(lo), float(la)) for s, lo, la in zip(feed.stops["stop_id"], feed.stops["stop_lon"],
                                                                 feed.stops["stop_lat"])}
    stop_routes: dict[str, set[str]] = defaultdict(set)
    for plan in tt_.trips.values():
        for s in plan.stop_ids:
            stop_routes[s].add(plan.route_id)
    hubs = find_hubs(tt_.stop_names, tt_.stop_xy, stop_routes)
    if hub is not None:
        hubs = {k: v for k, v in hubs.items() if slug(k) == hub}
    all_stops = sorted({s for v in hubs.values() for s in v})
    # planned departures at hub stops on the recorded service days, joined with the recorded ones
    ix = gtfs.departure_index()
    ints = [int(d.strftime("%Y%m%d")) for d in days]
    pl = ix[ix["stop_id"].isin(all_stops) & ix["service_date"].isin(ints)]
    pl = pl.assign(service_date=pd.to_datetime(pl["service_date"].astype(str)).dt.strftime("%Y-%m-%d"))
    obs = ev[ev["stop_id"].isin(all_stops)]
    lo, hi = cov["first"].timestamp(), cov["last"].timestamp()
    pl = pl[(pl["dep_ts"] >= lo + BEFORE_SEC) & (pl["dep_ts"] <= hi - AFTER_SEC)]
    dep = pl.merge(obs[["trip_id", "service_date", "stop_id", "dep"]], on=["trip_id", "service_date", "stop_id"],
                   how="left").rename(columns={"dep_ts": "p", "dep": "o"})
    a = obs.assign(t=obs["arr"].fillna(obs["dep"]), s=obs["sched_arr"])
    a = a[a["t"].notna() & (a["s"] >= lo + BEFORE_SEC) & (a["s"] <= hi - AFTER_SEC)]
    out = []
    for name, sids in hubs.items():
        walk = {}
        for x in sids:
            for y in sids:
                dxy = float(np.hypot(*(np.subtract(tt_.stop_xy[x], tt_.stop_xy[y]))))
                walk[(x, y)] = dxy / (WALK_KMH / 3.6) + BUFFER_SEC
        c = connections(a[a["stop_id"].isin(sids)][["trip_id", "service_date", "route_id", "stop_id", "t", "s"]],
                        dep[dep["stop_id"].isin(sids)], walk)
        if not len(c):
            continue
        ms, pw, rw, ew = _boot_stats(c, rng)
        pairs = []
        grp = c.groupby(["from_route", "to_route", "to_dir"])
        for (fa, tb, td), g in sorted(grp, key=lambda kv: (-kv[1]["missed"].mean() if len(kv[1]) >= dc.MIN_TRIPS
                                                            else 1.0, -len(kv[1]))):
            if len(pairs) >= (999 if hub else TOP_PAIRS):
                break
            p_ms, p_pw, p_rw, _ = _boot_stats(g, rng)
            pairs.append(TransferPair(fromRouteId=fa, fromShort=str(short.get(fa, fa)), toRouteId=tb,
                                      toShort=str(short.get(tb, tb)), toDirectionId=int(td), connections=len(g),
                                      missed=int(g["missed"].sum()), missedShare=p_ms, plannedWaitSec=p_pw,
                                      realWaitSec=p_rw))
        xs = [lonlat[s] for s in sids if s in lonlat]
        out.append(TransferHub(
            hubId=slug(name), name=name, location=[round(float(np.mean([p[0] for p in xs])), 6),
                                                   round(float(np.mean([p[1] for p in xs])), 6)],
            stopIds=sids, routes=sorted({r for s in sids for r in stop_routes[s]}), connections=len(c),
            missed=int(c["missed"].sum()), missedShare=ms, plannedWaitSec=pw, realWaitSec=rw, extraWaitSec=ew,
            pairs=pairs))
    out.sort(key=lambda h: -h.connections)
    if hub is None:
        out = out[:TOP_HUBS]
    provs = [prov.vehicles_provenance(cov["last"], f"{cov['labelRo']}; orarul observat (L0)"), feed.provenance]
    return TransferReport(status="ok", label=I18n(ro=cov["labelRo"], en=cov["labelEn"]), walk=walk_info, hubs=out,
                          method=METHOD, provenance=provs)


def job_key(hub: str | None) -> str:
    stems = store.built_stems()
    return f"transfers:v{ALGO_VERSION}:{hub}:{len(stems)}:{(stems or [''])[-1]}"


def respond_for(hub: str | None):
    return respond(job_key(hub), lambda: compute(hub))
