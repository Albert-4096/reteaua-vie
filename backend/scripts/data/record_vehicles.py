"""Record the CityApp live vehicles feed for the backend.

  DATA_DIR=... [LIVE_DIR=...] record_vehicles.py [--every 15]

Every 15 s: GET cont.primariatm.ro/api/mobile/transit/vehicles (undocumented,
no guarantee) and append one JSON line
  {fetchedAt, realtimeAgeSec, refreshInSec, vehicles: [...as served...]}
to $LIVE_DIR/vehicles/YYYYMMDD-HH.jsonl.gz (the UTC hour of fetchedAt), the
file app/common/vehicles.py reads. Each line is its own gzip member, so a crash
loses at most the line being written, and the reader skips a cut tail.
A failed poll writes nothing (a gap means unknown) and the next try waits 60 s.

Rules: never poll faster than every 10 s; one recorder per directory (a lock
file, and it will not start while another program writes there).
Runs until stopped (Ctrl-C); `make record` starts it in tmux.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_city  # noqa: E402  (sibling helper: http_get with the team's User-Agent)

VEHICLES_URL = "https://cont.primariatm.ro/api/mobile/transit/vehicles"
MIN_EVERY = 10
RETRY_AFTER = 60
BUSY_SECONDS = 30   # a recording file touched this recently means someone else records here


def hour_file(vdir: Path, t: datetime) -> Path:
    return vdir / f"{t.astimezone(UTC):%Y%m%d-%H}.jsonl.gz"


def snapshot(body: bytes, fetched_at: datetime) -> dict:
    data = json.loads(body)
    vehicles = data["vehicles"]
    if not isinstance(vehicles, list):
        raise ValueError("`vehicles` is not a list")
    return {
        "fetchedAt": fetched_at.astimezone(UTC).isoformat(timespec="seconds"),
        "realtimeAgeSec": data.get("realtimeAgeSec"),
        "refreshInSec": data.get("refreshInSec"),
        "vehicles": vehicles,
    }


def append(path: Path, snap: dict) -> None:
    """Append one line as a complete gzip member (readable while the hour is still open)."""
    line = (json.dumps(snap, ensure_ascii=False) + "\n").encode("utf-8")
    with path.open("ab") as f:
        f.write(gzip.compress(line))


def poll_once(vdir: Path) -> dict:
    resp = fetch_city.http_get(VEHICLES_URL, timeout=10)
    snap = snapshot(resp.body, datetime.now(UTC))
    append(hour_file(vdir, datetime.fromisoformat(snap["fetchedAt"])), snap)
    return snap


def someone_else_writing(vdir: Path) -> Path | None:
    recent = [p for p in vdir.glob("*.jsonl.gz") if time.time() - p.stat().st_mtime < BUSY_SECONDS]
    return recent[0] if recent else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--every", type=float, default=15.0, help=f"seconds between polls (min {MIN_EVERY})")
    args = parser.parse_args()
    if args.every < MIN_EVERY:
        parser.error(f"--every must be at least {MIN_EVERY} s (undocumented endpoint: be polite)")
    if not os.environ.get("DATA_DIR") and not os.environ.get("LIVE_DIR"):
        parser.error("set DATA_DIR (or LIVE_DIR)")
    live_dir = Path(os.environ.get("LIVE_DIR") or Path(os.environ["DATA_DIR"]) / "live").resolve()
    vdir = live_dir / "vehicles"
    vdir.mkdir(parents=True, exist_ok=True)

    lock = (vdir / ".recorder.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"another record_vehicles.py already records into {vdir}", file=sys.stderr)
        return 2
    busy = someone_else_writing(vdir)
    if busy is not None:
        print(f"{busy} was written less than {BUSY_SECONDS} s ago: another recorder writes into {vdir}. "
              "Not starting (two recorders would double the polls and the lines).", file=sys.stderr)
        return 2

    print(f"recording {VEHICLES_URL} every {args.every:g} s into {vdir}", flush=True)
    next_at = time.monotonic()
    while True:
        try:
            snap = poll_once(vdir)
            print(f"{snap['fetchedAt']} {len(snap['vehicles'])} vehicles", flush=True)
            next_at += args.every
        except KeyboardInterrupt:
            return 0
        except Exception as e:  # noqa: BLE001 (a failed poll is a gap, the recorder keeps going)
            print(f"{datetime.now(UTC).isoformat(timespec='seconds')} poll failed: {type(e).__name__}: {e}",
                  flush=True)
            next_at = time.monotonic() + RETRY_AFTER
        if next_at < time.monotonic():   # fell behind: never burst to catch up
            next_at = time.monotonic() + args.every
        try:
            time.sleep(next_at - time.monotonic())
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main())
