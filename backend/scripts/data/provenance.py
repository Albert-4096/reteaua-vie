"""Write per-source provenance records and merge them into sources.json.

  provenance.py part DATA_DIR ID FILE --source S --url U --version V --license L
                     [--note N] [--upstream-file F] [--upstream-url U]
  provenance.py merge DATA_DIR

`part` writes $DATA_DIR/provenance/parts/ID.json for a file fetched by
fetch_all.sh. `fetchedAt` is the mtime of the downloaded file (the upstream
file when given), so a rerun that downloads nothing keeps the same value.

`merge` writes $DATA_DIR/provenance/sources.json: the fetched sources (the
parts written here and by fetch_city.py) plus an inventory (size, sha256,
mtime) of every GTFS zip and city-API file on disk.

Each record carries the CONTRACT Provenance fields (source, url, version,
fetchedAt, note) plus id, license, file, bytes, sha256.
"""

import argparse
import csv
import hashlib
import io
import json
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def mtime_iso(path: Path) -> str:
    ts = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return ts.isoformat(timespec="seconds").replace("+00:00", "Z")


def file_record(data_dir: Path, path: Path) -> dict:
    return {
        "file": str(path.relative_to(data_dir)),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def cmd_part(args: argparse.Namespace) -> None:
    data_dir = Path(args.data_dir)
    path = data_dir / args.file
    record = {
        "id": args.id,
        "source": args.source,
        "url": args.url,
        "version": args.version,
        "fetchedAt": mtime_iso(data_dir / args.upstream_file if args.upstream_file else path),
        "note": args.note or None,
        "license": args.license,
        **file_record(data_dir, path),
    }
    if args.upstream_file:
        record["upstream"] = {"url": args.upstream_url, **file_record(data_dir, data_dir / args.upstream_file)}
    parts = data_dir / "provenance" / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    (parts / f"{args.id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print(f"  provenance {args.id}: {record['file']} {record['bytes']} B sha256={record['sha256']}")


def gtfs_version(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as z:
            rows = list(csv.DictReader(io.TextIOWrapper(z.open("feed_info.txt"), encoding="utf-8-sig")))
    except (KeyError, zipfile.BadZipFile):
        return None
    return rows[0].get("feed_version") if rows else None


def local_inventory(data_dir: Path) -> list[dict]:
    """Every GTFS zip and city-API file on disk (fetch_city.py fetches the newest ones)."""
    records = []
    gtfs = sorted(data_dir.glob("smtt-*.zip")) + sorted((data_dir / "live" / "gtfs").glob("*.zip"))
    for path in gtfs:
        records.append({
            "id": f"gtfs:{path.name}",
            "source": "SMTT GTFS",
            "url": None,
            "version": gtfs_version(path),
            "fetchedAt": mtime_iso(path),
            "note": "inventory of the local file; fetchedAt = file mtime",
            "license": None,
            **file_record(data_dir, path),
        })
    for path in sorted(data_dir.glob("city-api-*/*")):
        if path.is_file():
            records.append({
                "id": f"city-api:{path.parent.name}/{path.name}",
                "source": "Primăria Timișoara city API (cache)",
                "url": None,
                "version": path.parent.name.removeprefix("city-api-"),
                "fetchedAt": mtime_iso(path),
                "note": "inventory of the local file; fetchedAt = file mtime",
                "license": None,
                **file_record(data_dir, path),
            })
    return records


def cmd_merge(args: argparse.Namespace) -> None:
    merge(Path(args.data_dir), "backend/scripts/data/fetch_all.sh")


def merge(data_dir: Path, generated_by: str) -> None:
    parts = sorted((data_dir / "provenance" / "parts").glob("*.json"))
    fetched = [json.loads(p.read_text()) for p in parts]
    out = {
        "generatedAt": datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "generatedBy": generated_by,
        "dataFreeze": os.environ.get("DATA_FREEZE") == "1",
        "fetched": fetched,
        "local": local_inventory(data_dir),
    }
    target = data_dir / "provenance" / "sources.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(target)
    print(f"wrote {target}: {len(fetched)} fetched, {len(out['local'])} local")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("part")
    p.add_argument("data_dir")
    p.add_argument("id")
    p.add_argument("file", help="path relative to DATA_DIR")
    p.add_argument("--source", required=True)
    p.add_argument("--url", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--license", required=True)
    p.add_argument("--note")
    p.add_argument("--upstream-file", help="downloaded file this one was derived from, relative to DATA_DIR")
    p.add_argument("--upstream-url")
    p.set_defaults(func=cmd_part)
    m = sub.add_parser("merge")
    m.add_argument("data_dir")
    m.set_defaults(func=cmd_merge)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
