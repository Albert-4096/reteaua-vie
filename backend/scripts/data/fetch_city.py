"""Fetch the city sources the backend reads, into $DATA_DIR and $LIVE_DIR.

  DATA_DIR=... [LIVE_DIR=...] fetch_city.py [--only gtfs,stpt,...] [--every SECONDS]

Sources (GET only, a User-Agent that names the team; never live.stpt.ro):
  gtfs      SMTT GTFS zip                     -> $LIVE_DIR/gtfs/smtt_<etag>.zip (a new file only when it changed)
  history   GTFS 4.29 and 4.30, Mobility Database mirror of the SMTT zip, pinned by sha256
                                              -> $DATA_DIR/gtfs-history/ (downloaded once)
  network   cont.primariatm.ro/api/mobile/transit/network
                                              -> $DATA_DIR/city-api-2026-11-13/transit-network.json
  zones     cont.primariatm.ro/api/zones      -> .../zones.geojson
  parking   cont.primariatm.ro/api/mobile/parking -> .../parking.json
  streets   servicii.primariatm.ro/api/nomenclator/strazi -> .../nomenclator-strazi.json
  stpt      stpt.ro WordPress API, newest 20 posts -> $LIVE_DIR/stpt-posts/<id>_<modified>.json (new or edited)
  sesizari  sesizari.primariatm.ro/api/sesizari, last 2 days, without the report text
                                              -> $LIVE_DIR/sesizari/YYYYMMDD-HHMM.json (UTC)

Every download lands in a staging dir and is checked first (JSON shape and
counts; zip CRC, required GTFS files and feed_info.txt). Only a checked file
replaces the real one, by an atomic rename. When a source fails, the last good
file stays and its provenance note says „memorat, sursa indisponibilă”.
DATA_FREEZE=1 downloads nothing and only rewrites the provenance records.

Provenance: one record per source in $DATA_DIR/provenance/parts/, merged into
$DATA_DIR/provenance/sources.json (the format fetch_all.sh writes).
Exit status 1 when a source failed and there is no earlier file for it.
Standard library only, so it runs without the backend's environment.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import provenance  # noqa: E402  (sibling helper; this script runs with python -I)

USER_AGENT = "ReteauaVie/1.0 (UniHack 8, team The Bloom)"
TZ = ZoneInfo("Europe/Bucharest")
KEPT = "memorat, sursa indisponibilă"
# The directory app/config.py reads (Settings.city_dir); its name is the date of the first copy.
CITY_DIR = "city-api-2026-11-13"

GTFS_URL = "https://smtt.ro/transit/gtfs/maps/smtt-timisoara-ro.zip"
GTFS_REQUIRED = ("routes.txt", "stops.txt", "trips.txt", "stop_times.txt", "feed_info.txt")
# Older SMTT feeds, the timetable before a diversion (Mobility Database mirror, dataset mdb-2868).
GTFS_HISTORY = (
    ("smtt-4.29_mdb-2868-202610240049.zip",
     "https://files.mobilitydatabase.org/mdb-2868/mdb-2868-202610240049/mdb-2868-202610240049.zip",
     "1b2b4b212cea5a04a257011f5b64c69b3ad4cfa2adbd8dccf3bf5b561b9ab35a"),
    ("smtt-4.30_mdb-2868-202611020102.zip",
     "https://files.mobilitydatabase.org/mdb-2868/mdb-2868-202611020102/mdb-2868-202611020102.zip",
     "cfeb2098580ed4dd0896f34a0db45aa7833caa18e1c384e64b659ce3d8f4f7ca"),
)
STPT_URL = "https://stpt.ro/wp-json/wp/v2/posts"
STPT_FIELDS = ("id", "date", "modified", "link", "title", "content", "categories")
STPT_PER_PAGE = 20
SESIZARI_URL = "https://sesizari.primariatm.ro/api/sesizari"
SESIZARI_DAYS_BACK = 2   # app/live/reports.py assumes startDate = poll day (Bucharest) - 2 days
# Kept per report: what the backend counts, without the free text (it can hold names).
SESIZARI_KEEP = ("id", "webconInstanceNr", "createdAt", "status", "categorii", "subcategorii", "locatie")

GTFS_LABEL = "SMTT GTFS (orar planificat / planned timetable)"
HISTORY_LABEL = "SMTT GTFS, Mobility Database mirror (mdb-2868)"
CITY_LABEL = "Primăria Timișoara city API"
STPT_LABEL = "STPT, anunțuri / notices (stpt.ro WordPress API)"
SESIZARI_LABEL = "Primăria Timișoara, sesizări publice (fără text / without text)"
CITY_LICENSE = "public City Hall endpoint, no licence stated"


# --- HTTP ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]     # lower-case names
    body: bytes


def _ipv4_first(*args, **kwargs):
    return sorted(_getaddrinfo(*args, **kwargs), key=lambda a: a[0] != socket.AF_INET)


# Try IPv4 addresses first (IPv6 stays the fallback): on a host without an IPv6
# route, urllib would otherwise wait the whole timeout on the AAAA address.
_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = _ipv4_first


def http_get(url: str, headers: dict[str, str] | None = None, timeout: float = 60) -> Response:
    """One GET with the team's User-Agent, at most `timeout` seconds in all.

    304 is returned; other HTTP errors raise.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    deadline = time.monotonic() + timeout
    try:
        with urllib.request.urlopen(req, timeout=min(timeout, 20)) as r:
            chunks = []
            while chunk := r.read(1 << 16):
                chunks.append(chunk)
                if time.monotonic() > deadline:
                    raise TimeoutError(f"{url}: slower than {timeout:g} s")
            return Response(r.status, {k.lower(): v for k, v in r.headers.items()}, b"".join(chunks))
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return Response(304, {k.lower(): v for k, v in e.headers.items()}, b"")
        raise


def get_json(url: str) -> Any:
    resp = http_get(url)
    try:
        return json.loads(resp.body)
    except ValueError as e:
        raise ValueError(f"not JSON ({resp.headers.get('content-type')}, {len(resp.body)} B)") from e


# --- checks: a summary line for the log, or an exception -----------------------------


def check_network(d: dict) -> str:
    n = {k: len(d[k]) for k in ("routes", "stops", "paths")}
    if not d.get("feedVersion") or not all(n.values()):
        raise ValueError(f"empty network: {n}")
    return f"feedVersion {d['feedVersion']}: {n['routes']} lines, {n['stops']} stops, {n['paths']} paths"


def check_zones(d: dict) -> str:
    feats = d["features"]
    if d.get("type") != "FeatureCollection" or not feats:
        raise ValueError("no zones")
    if any(not f["properties"].get("slug") or not f["geometry"]["coordinates"] for f in feats):
        raise ValueError("a zone without slug or geometry")
    return f"{len(feats)} zones"


def check_parking(d: dict) -> str:
    feats = d["features"]
    if not feats or any(not f["kind"] or not f["coordinates"] for f in feats):
        raise ValueError("no parking features, or one without kind / coordinates")
    kinds: dict[str, int] = {}
    for f in feats:
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    return f"version {d.get('version')}: {len(feats)} features " + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))


def check_streets(d: dict) -> str:
    rows = d["strazi"]
    if not rows:
        raise ValueError("empty street register")
    return f"{len(rows)} streets ({d.get('activeCount')} active)"


def check_posts(posts: list) -> str:
    if not isinstance(posts, list) or not posts:
        raise ValueError("no posts")
    for p in posts:
        missing = [k for k in STPT_FIELDS if k not in p]
        if missing:
            raise ValueError(f"post {p.get('id')} lacks {missing}")
    return f"{len(posts)} posts, newest {posts[0]['id']} ({posts[0]['modified']})"


def check_sesizari(rows: list) -> str:
    if not isinstance(rows, list):
        raise ValueError("not a list")
    if any("id" not in r or "createdAt" not in r for r in rows):
        raise ValueError("a report without id / createdAt")
    return f"{len(rows)} reports"


def gtfs_summary(path: Path) -> tuple[str | None, str]:
    """(feed_version, summary). Raises on a corrupt zip or a missing required file."""
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            raise ValueError(f"CRC error in {bad}")
        names = set(z.namelist())
        missing = [n for n in GTFS_REQUIRED if n not in names]
        if missing or not names & {"calendar.txt", "calendar_dates.txt"}:
            raise ValueError(f"not a GTFS feed, missing {missing or 'calendar'}")

        def rows(name: str) -> list[dict]:
            return list(csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig")))

        info = rows("feed_info.txt")
        if not info:
            raise ValueError("empty feed_info.txt")
        routes = {r["route_id"] for r in rows("routes.txt")}
        stops = {r["stop_id"] for r in rows("stops.txt")}
    if not routes or not stops:
        raise ValueError("no routes or stops")
    i = info[0]
    return i.get("feed_version"), (f"feed_version {i.get('feed_version')}, valid {i.get('feed_start_date')}"
                                   f"-{i.get('feed_end_date')}: {len(routes)} routes, {len(stops)} stops")


# --- files and provenance ------------------------------------------------------------


def log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def install(staged: Path, target: Path) -> None:
    """Copy a checked file into place: written next to the target, then renamed (atomic)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(f".{target.name}.part")
    shutil.copyfile(staged, part)
    os.replace(part, target)


def same_bytes(a: Path, b: Path) -> bool:
    return b.is_file() and a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()


class Run:
    """One fetch run: paths, the staging dir and the provenance records it writes."""

    def __init__(self, data_dir: Path, live_dir: Path, staging: Path, freeze: bool):
        self.data_dir, self.live_dir, self.staging, self.freeze = data_dir, live_dir, staging, freeze
        self.failed: list[str] = []

    def rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.data_dir))
        except ValueError:
            return str(path)

    def record(self, rid: str, path: Path, *, source: str, url: str, version: str | None, note: str | None,
               license: str) -> None:
        """Write $DATA_DIR/provenance/parts/<rid>.json; fetchedAt = the file's mtime (when we got it)."""
        rec = {
            "id": rid, "source": source, "url": url, "version": version,
            "fetchedAt": provenance.mtime_iso(path), "note": note, "license": license,
            "file": self.rel(path), "bytes": path.stat().st_size, "sha256": provenance.sha256(path),
        }
        parts = self.data_dir / "provenance" / "parts"
        parts.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9._-]", "_", rid)
        (parts / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def stage(self, name: str, body: bytes) -> Path:
        path = self.staging / name
        path.write_bytes(body)
        return path

    def fail(self, sid: str, err: BaseException, have_old: bool) -> str | None:
        """Log a failed source. Returns the provenance note (or marks the run failed)."""
        log(f"FAILED {sid}: {type(err).__name__}: {err}")
        if have_old:
            log(f"{sid}: keeping the last good file ({KEPT})")
            return KEPT
        self.failed.append(sid)
        return None


# --- sources -------------------------------------------------------------------------


@dataclass(frozen=True)
class CityFile:
    id: str
    url: str
    file: str                                 # name in $DATA_DIR/city-api-2026-11-13/
    check: Callable[[Any], str]
    version: Callable[[Any], str | None]


CITY_FILES = (
    CityFile("network", "https://cont.primariatm.ro/api/mobile/transit/network", "transit-network.json",
             check_network, lambda d: d.get("feedVersion")),
    CityFile("zones", "https://cont.primariatm.ro/api/zones", "zones.geojson", check_zones, lambda d: None),
    CityFile("parking", "https://cont.primariatm.ro/api/mobile/parking", "parking.json",
             check_parking, lambda d: None if d.get("version") is None else str(d["version"])),
    CityFile("streets", "https://servicii.primariatm.ro/api/nomenclator/strazi", "nomenclator-strazi.json",
             check_streets, lambda d: None),
)


def fetch_city_file(run: Run, src: CityFile) -> None:
    """A city endpoint copied as served; replaced only when the checked body differs."""
    target = run.data_dir / CITY_DIR / src.file
    note = None
    if not run.freeze:
        try:
            body = http_get(src.url).body
            data = json.loads(body)
            log(f"{src.id}: {src.check(data)}")
            staged = run.stage(src.file, body)
            if same_bytes(staged, target):
                log(f"{src.id}: unchanged, keeping {run.rel(target)}")
            else:
                install(staged, target)
                log(f"{src.id}: wrote {run.rel(target)} ({len(body)} B)")
        except Exception as e:  # noqa: BLE001 (any failure keeps the last good file)
            note = run.fail(src.id, e, target.is_file())
    if not target.is_file():
        if run.freeze:
            run.failed.append(src.id)
            log(f"{src.id}: DATA_FREEZE=1 and {run.rel(target)} is missing")
        return
    try:
        version = src.version(json.loads(target.read_bytes()))
    except Exception:  # noqa: BLE001
        version = None
    run.record(f"city-{src.id}", target, source=f"{CITY_LABEL} ({src.url.split('/api/', 1)[1]})", url=src.url,
               version=version, note=note, license=CITY_LICENSE)


def _etag_name(etag: str | None, body_sha: str) -> str:
    tag = re.sub(r"[^A-Za-z0-9.-]", "", (etag or "").removeprefix("W/"))
    return f"smtt_{tag}.zip" if tag else f"smtt_sha-{body_sha[:12]}.zip"


def newest_zip(d: Path) -> Path | None:
    """The zip app/common/gtfs.py serves: the newest by mtime."""
    zips = sorted(d.glob("*.zip"), key=lambda p: p.stat().st_mtime) if d.is_dir() else []
    return zips[-1] if zips else None


def fetch_gtfs(run: Run) -> None:
    gdir = run.live_dir / "gtfs"
    current = newest_zip(gdir)
    note = None
    if not run.freeze:
        try:
            headers = {}
            m = re.fullmatch(r"smtt_(?!sha-)(.+)\.zip", current.name) if current else None
            if m:
                headers["If-None-Match"] = f'"{m.group(1)}"'
            resp = http_get(GTFS_URL, headers=headers, timeout=120)
            if resp.status == 304:
                log(f"gtfs: not modified (ETag {m.group(1)}), keeping {run.rel(current)}")
            else:
                sha = hashlib.sha256(resp.body).hexdigest()
                staged = run.stage("gtfs.zip", resp.body)
                version, summary = gtfs_summary(staged)
                log(f"gtfs: {summary}")
                same = next((p for p in gdir.glob("*.zip") if provenance.sha256(p) == sha), None) \
                    if gdir.is_dir() else None
                if same is not None:
                    log(f"gtfs: same bytes as {run.rel(same)}, nothing new")
                else:
                    target = gdir / _etag_name(resp.headers.get("etag"), sha)
                    old = provenance.gtfs_version(current) if current else None
                    install(staged, target)
                    current = target
                    log(f"gtfs: new feed {run.rel(target)} (feed_version {old} -> {version})")
        except Exception as e:  # noqa: BLE001
            note = run.fail("gtfs", e, current is not None)
    if current is None:
        if run.freeze:
            run.failed.append("gtfs")
            log("gtfs: DATA_FREEZE=1 and no zip in $LIVE_DIR/gtfs")
        return
    run.record("smtt-gtfs", current, source=GTFS_LABEL, url=GTFS_URL, version=provenance.gtfs_version(current),
               note=note, license="SMTT open data (GTFS), no licence stated")


def fetch_history(run: Run) -> None:
    """Pinned older feeds: downloaded only when missing, accepted only with the pinned sha256."""
    hdir = run.data_dir / "gtfs-history"
    for name, url, pinned in GTFS_HISTORY:
        target = hdir / name
        if not target.is_file() and not run.freeze:
            try:
                body = http_get(url, timeout=120).body
                sha = hashlib.sha256(body).hexdigest()
                if sha != pinned:
                    raise ValueError(f"sha256 {sha[:12]} is not the pinned {pinned[:12]}")
                staged = run.stage(name, body)
                gtfs_summary(staged)
                install(staged, target)
                log(f"history: downloaded {name}")
            except Exception as e:  # noqa: BLE001
                run.fail(f"history {name}", e, False)
                continue
        if not target.is_file():
            if run.freeze:
                run.failed.append(f"history {name}")
            continue
        log(f"history: {name}: {gtfs_summary(target)[1]}")
        run.record(f"gtfs-history:{name}", target, source=HISTORY_LABEL, url=url,
                   version=provenance.gtfs_version(target), note=None,
                   license="SMTT open data (GTFS), no licence stated")


def post_file_name(post: dict) -> str:
    """<id>_<modified as YYYYMMDDTHHMMSS>.json: an edited post gets a new file."""
    return f"{int(post['id'])}_{re.sub(r'[-:]', '', post['modified'])}.json"


def fetch_stpt(run: Run) -> None:
    pdir = run.live_dir / "stpt-posts"
    note = None
    if not run.freeze:
        try:
            url = f"{STPT_URL}?per_page={STPT_PER_PAGE}&_fields={','.join(STPT_FIELDS)}"
            posts = get_json(url)
            log(f"stpt: {check_posts(posts)}")
            new = 0
            for post in posts:
                target = pdir / post_file_name(post)
                if target.is_file():
                    continue
                post = {k: post[k] for k in STPT_FIELDS}
                staged = run.stage(target.name, json.dumps(post, ensure_ascii=False, indent=1).encode("utf-8"))
                install(staged, target)
                new += 1
                log(f"stpt: new or edited post {post['id']}: {post['title'].get('rendered', '')[:70]}")
            log(f"stpt: {new} new files in {run.rel(pdir)}")
        except Exception as e:  # noqa: BLE001
            note = run.fail("stpt", e, any(pdir.glob("*.json")) if pdir.is_dir() else False)
    files = sorted(pdir.glob("*.json"), key=lambda p: p.stat().st_mtime) if pdir.is_dir() else []
    if not files:
        if run.freeze:
            run.failed.append("stpt")
        return
    run.record("stpt-posts", files[-1], source=STPT_LABEL, url=STPT_URL,
               version=f"{len(files)} saved posts", note=note, license="stpt.ro, public notices")


def fetch_sesizari(run: Run, now: datetime | None = None) -> None:
    sdir = run.live_dir / "sesizari"
    note = None
    if not run.freeze:
        now = now or datetime.now(UTC)
        day = now.astimezone(TZ).date()
        start, end = day - timedelta(days=SESIZARI_DAYS_BACK), day + timedelta(days=1)
        try:
            rows = get_json(f"{SESIZARI_URL}?startDate={start.isoformat()}&endDate={end.isoformat()}")
            log(f"sesizari: {check_sesizari(rows)} ({start} to {end})")
            rows = [{k: r[k] for k in SESIZARI_KEEP if k in r} for r in rows]
            name = f"{now.astimezone(UTC):%Y%m%d-%H%M}.json"
            install(run.stage(name, json.dumps(rows, ensure_ascii=False).encode("utf-8")), sdir / name)
            log(f"sesizari: wrote {run.rel(sdir / name)}")
        except Exception as e:  # noqa: BLE001
            note = run.fail("sesizari", e, any(sdir.glob("*.json")) if sdir.is_dir() else False)
    files = sorted(sdir.glob("*.json")) if sdir.is_dir() else []
    if files:
        run.record("city-sesizari", files[-1], source=SESIZARI_LABEL, url=SESIZARI_URL, version=None, note=note,
                   license=CITY_LICENSE)


SOURCES: dict[str, Callable[[Run], None]] = {
    "gtfs": fetch_gtfs,
    "history": fetch_history,
    **{s.id: (lambda run, s=s: fetch_city_file(run, s)) for s in CITY_FILES},
    "stpt": fetch_stpt,
    "sesizari": fetch_sesizari,
}


def run_once(data_dir: Path, live_dir: Path, only: list[str], freeze: bool) -> list[str]:
    """Fetch the chosen sources; returns the ids that failed with no earlier file."""
    with tempfile.TemporaryDirectory(prefix="fetch-city-") as tmp:
        run = Run(data_dir, live_dir, Path(tmp), freeze)
        for sid in only:
            print(f"== {sid}", flush=True)
            SOURCES[sid](run)
    provenance.merge(data_dir, "backend/scripts/data/fetch_city.py")
    return run.failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", default=",".join(SOURCES), help=f"comma list of {', '.join(SOURCES)}")
    parser.add_argument("--every", type=int, default=0, help="repeat every N seconds (min 600); 0 = once")
    args = parser.parse_args()
    only = [s.strip() for s in args.only.split(",") if s.strip()]
    unknown = [s for s in only if s not in SOURCES]
    if unknown:
        parser.error(f"unknown source {unknown}; choose from {', '.join(SOURCES)}")
    if args.every and args.every < 600:
        parser.error("--every must be at least 600 s (be polite to the city servers)")
    if not os.environ.get("DATA_DIR"):
        parser.error("set DATA_DIR to the data directory")
    data_dir = Path(os.environ["DATA_DIR"]).resolve()
    live_dir = Path(os.environ.get("LIVE_DIR") or data_dir / "live").resolve()
    freeze = os.environ.get("DATA_FREEZE", "").strip() in ("1", "true", "yes")
    print(f"DATA_DIR={data_dir} LIVE_DIR={live_dir} DATA_FREEZE={int(freeze)} sources={','.join(only)}", flush=True)
    while True:
        started = time.monotonic()
        try:
            failed = run_once(data_dir, live_dir, only, freeze)
        except Exception:  # noqa: BLE001 (the loop keeps going; a single run fails loud)
            if not args.every:
                raise
            traceback.print_exc()
            failed = []
        if failed:
            print(f"FAILED with no earlier file: {', '.join(failed)}", flush=True)
        if not args.every:
            return 1 if failed else 0
        time.sleep(max(60.0, args.every - (time.monotonic() - started)))


if __name__ == "__main__":
    sys.exit(main())
