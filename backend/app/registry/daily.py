"""R14: the daily registry of trips seen, with a hash chain.

One file per recorded local day under $DATA_DIR/registry/YYYYMMDD.json, written once and never rewritten:
per line the trips in the timetable, the trips seen (L0, `app.observed.store.events`), their share and the
km „estimare”; the recording health; the sha256 of the day's raw recording files and of the rollup, chained
to the previous day. Today and a day whose hours L0 has not built yet are shown but not written (`final: false`).
Retention is a proposal, not a legal claim: raw files until the 20th of the next month (art. 12.5 of the
contract), rollups 13 months (art. 12.9)."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from app.cityapp import km
from app.common import gtfs, vehicles
from app.common import provenance as prov
from app.common.city import load_network, route_mode
from app.common.timeutil import iso, local_midnight, parse_iso
from app.config import TZ, get_settings, now, real_now
from app.evidence.journal import canon, sha
from app.live import missing
from app.m1_disruption import impact as imp
from app.observed import store as observed

GENESIS = "0" * 64
ROLLUP_VERSION = 2   # 2: trips seen = seen ∩ scheduled in the compared recording span (L8b); tripsSeenOutside, vehiclesSeen
MODE_LABEL = {"tram": "tramvai", "bus": "autobuz", "trolleybus": "troleibuz"}


def _dir() -> Path:
    d = get_settings().data_dir / "registry"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file_sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def recorded_days() -> list[date]:
    return sorted({h.astimezone(TZ).date() for _p, h in vehicles.recording_files()})


def _raw_files(day: date) -> list[tuple[Path, datetime]]:
    return [(p, h) for p, h in vehicles.recording_files() if h.astimezone(TZ).date() == day]


def _stored(day: date) -> dict | None:
    p = _dir() / f"{day:%Y%m%d}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def _previous_hash(day: date) -> str:
    prev = [d for d in recorded_days() if d < day and _stored(d)]
    return _stored(prev[-1])["chainHash"] if prev else GENESIS


def day_core(day: date) -> dict:
    """What one local day's trip counts rest on: the recording span, the compared span, and the day's scheduled
    trips inside it with a `seen` flag. The only rule for „trips seen” (registry and /api/reliability/lines):
    a trip is counted when it is scheduled to start inside the compared recording span and L0 saw it. A trip seen
    that started before the recording began (still running in its first snapshots) is not counted: `seenOutside`."""
    files = _raw_files(day)
    d0 = local_midnight(day)
    d1 = d0 + timedelta(days=1)
    snaps, _ = missing.recorded(d0, d1)
    first = datetime.fromtimestamp(snaps[0].ts, tz=TZ) if snaps else None
    last = datetime.fromtimestamp(snaps[-1].ts, tz=TZ) if snaps else None
    healthy = None
    if snaps:
        span = max(1, int((snaps[-1].ts - snaps[0].ts) // 60) + 1)
        healthy = round(len(missing._healthy_minutes(snaps, snaps[0].ts)) / span, 4)

    f = gtfs.feed(d0)
    trips, _ = missing.scheduled_trips(f, d0, d1)
    trips = trips[trips.day == day]
    seen_events = observed.events()
    seen_events = seen_events[seen_events["service_date"].astype(str) == day.isoformat()] if len(seen_events) else seen_events
    stems_built = set(observed.built_stems())
    stems_needed = {f"{h.astimezone(timezone_utc()):%Y%m%d-%H}" for _p, h in files}
    complete = stems_needed <= stems_built
    # L0 covers whole hours: trips are compared only up to the end of the last built hour (the open hour is not built)
    built_here = sorted(h for _p, h in files if f"{h.astimezone(timezone_utc()):%Y%m%d-%H}" in stems_built)
    l0_end = (built_here[-1] + timedelta(hours=1)).timestamp() if built_here else None
    compare_end = last.timestamp() if last is not None and complete else (min(last.timestamp(), l0_end) if last is not None and l0_end else None)
    if first is not None and compare_end is not None:
        rec = trips[(trips.start_ts >= first.timestamp()) & (trips.start_ts <= compare_end)]
    else:
        rec = trips.iloc[0:0]
    seen_ids = set(seen_events["trip_id"]) if len(seen_events) else set()
    rec = rec.assign(seen=rec.trip_id.isin(seen_ids))
    return {"files": files, "first": first, "last": last, "healthy": healthy, "f": f, "trips": trips, "rec": rec,
            "events": seen_events, "complete": complete, "compare_end": compare_end}


def recorded_trips(days: list[date] | None = None) -> pd.DataFrame:
    """Scheduled trips inside the compared recording span of every recorded day, with `seen` (day_core's rule)."""
    parts = []
    for d in days or recorded_days():
        r = day_core(d)["rec"]
        if len(r):
            parts.append(r.assign(local_day=d))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
        {"route_id": [], "direction_id": [], "trip_id": [], "start_ts": [], "seen": [], "local_day": []})


def compute(day: date) -> dict:
    """The entry of one local day, from the raw files and L0. Pure: the same inputs give the same hashes."""
    core = day_core(day)
    files, first, last, healthy, f = core["files"], core["first"], core["last"], core["healthy"], core["f"]
    trips, rec, seen_events = core["trips"], core["rec"], core["events"]
    complete, compare_end = core["complete"], core["compare_end"]
    raw_lines = [f"{p.name}:{_file_sha(p)}" for p, _ in files]
    net = load_network()

    tt = imp.current_timetable()
    lines: dict[str, dict] = {}
    for rid, g in trips.groupby("route_id"):
        lines[rid] = {"scheduled": int(len(g)), "scheduledRec": 0}
    rec_ids = set(rec.trip_id)
    for rid, g in rec.groupby("route_id"):
        lines[rid]["scheduledRec"] = int(len(g))
    seen: dict[str, set] = {}
    seen_dir: dict[tuple[str, int], set] = {}
    outside: dict[str, set] = {}
    for r in seen_events[["route_id", "direction_id", "trip_id"]].drop_duplicates().itertuples(index=False):
        if r.trip_id in rec_ids:
            seen.setdefault(r.route_id, set()).add(r.trip_id)
            seen_dir.setdefault((r.route_id, int(r.direction_id)), set()).add(r.trip_id)
        else:
            outside.setdefault(r.route_id, set()).add(r.trip_id)
        lines.setdefault(r.route_id, {"scheduled": 0, "scheduledRec": 0})
    vehicles_of = seen_events.groupby('route_id')['vehicle_id'].nunique().to_dict() if len(seen_events) else {}
    out = []
    for rid, ln in sorted(lines.items()):
        route = net.route_by_id.get(rid) or {}
        km_est = 0.0
        for dr in (0, 1):
            shape = km._shape(tt, rid, dr)
            if shape is not None:
                km_est += len(seen_dir.get((rid, dr), ())) * shape.length / 1000.0
        n_seen = len(seen.get(rid, ()))
        out.append({"routeId": rid, "shortName": route.get("shortName"), "mode": MODE_LABEL.get(route_mode(rid)),
                    "tripsScheduled": ln["scheduled"], "tripsScheduledInRecording": ln["scheduledRec"], "tripsSeen": n_seen,
                    "tripsSeenOutside": len(outside.get(rid, ())),
                    "vehiclesSeen": int(vehicles_of.get(rid, 0)),
                    "share": round(n_seen / ln["scheduledRec"], 4) if ln["scheduledRec"] else None,
                    "kmEstimated": round(km_est, 1), "kmNote": "estimare: curse văzute × lungimea traseului GTFS"})
    recording = {"firstAt": iso(first) if first else None, "lastAt": iso(last) if last else None,
                 "healthyShare": healthy, "files": [p.name for p, _ in files], "l0Complete": complete,
                 "comparedUntil": iso(datetime.fromtimestamp(compare_end, tz=TZ)) if compare_end else None}
    rollup = {"date": day.isoformat(), "recording": recording, "lines": out, "feedVersion": f.version, "rollupVersion": ROLLUP_VERSION}
    raw_sha = sha("\n".join(sorted(raw_lines)))
    rollup_sha = sha(canon(rollup))
    return {**rollup, "rawSha256": raw_sha, "rollupSha256": rollup_sha}


def timezone_utc():
    from datetime import timezone
    return timezone.utc


def entry(day: date, verify: bool = False) -> dict:
    stored = _stored(day)
    if stored is not None and stored.get("rollupVersion") != ROLLUP_VERSION:
        # an older rollup counted trips by another rule: recompute it, after the days before it (the chain)
        for d in [d for d in recorded_days() if d < day]:
            entry(d)
        stored = None
    if stored is not None:
        out = {**stored, "final": True}
        if verify:
            again = compute(day)
            out["verified"] = again["rawSha256"] == stored["rawSha256"] and again["rollupSha256"] == stored["rollupSha256"]
        return out
    e = compute(day)
    prev = _previous_hash(day)
    e = {**e, "prevHash": prev, "chainHash": sha(prev + e["rawSha256"] + e["rollupSha256"])}
    past = day < real_now().astimezone(TZ).date()
    if past and e["recording"]["l0Complete"] and e["recording"]["files"]:
        p = _dir() / f"{day:%Y%m%d}.json"
        fd, tmp = tempfile.mkstemp(dir=_dir(), prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(e, fh, ensure_ascii=False)
        os.chmod(tmp, 0o664)
        os.replace(tmp, p)
        return {**e, "final": True}
    return {**e, "final": False}


def registry(start: date, end: date, verify: bool = False) -> dict:
    days = [d for d in recorded_days() if start <= d <= end]
    entries = [entry(d, verify) for d in days]
    note = ("Registrul zilnic al curselor văzute în datele live ale Primăriei, înregistrate de noi. „Văzute” = apar în "
            "înregistrare, nu „efectuate”: clasificarea cursei o face SMTT. Zilele trecute se scriu o dată și nu se mai "
            "rescriu; fiecare zi poartă hash-ul zilei dinainte. Înregistrarea a început pe 13 nov (zile parțiale, vezi "
            "`recording`). Retenția (fișiere brute până pe 20 a lunii următoare, agregate 13 luni) este o propunere, nu o "
            "afirmație juridică. `kmEstimated` este estimare.")
    return {"entries": entries,
            "provenance": [prov.provenance("Rețeaua Vie, registrul curselor / trips registry", iso(now()), None, None, note).model_dump()]}
