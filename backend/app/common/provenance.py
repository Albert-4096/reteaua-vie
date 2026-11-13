"""Provenance: source + date next to every figure (CONTRACT "Conventions").

Build entries with `provenance(...)`; the per-source helpers below fill in the
source name, URL, version and the fetch time of the local file we serve.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.common.timeutil import file_mtime, iso, parse_iso
from app.models.base import Provenance

CITY_TRANSIT_URL = "https://cont.primariatm.ro/api/mobile/transit/network"
CITY_ZONES_URL = "https://cont.primariatm.ro/api/zones"
CITY_PARKING_URL = "https://cont.primariatm.ro/api/mobile/parking"
CITY_VEHICLES_URL = "https://cont.primariatm.ro/api/mobile/transit/vehicles"
SMTT_GTFS_URL = "https://smtt.ro"
STPT_POSTS_URL = "https://stpt.ro/wp-json/wp/v2/posts"


def provenance(
    source: str,
    fetched_at: datetime | str,
    url: str | None = None,
    version: str | None = None,
    note: str | None = None,
) -> Provenance:
    fetched = fetched_at if isinstance(fetched_at, str) else iso(fetched_at)
    return Provenance(source=source, url=url, version=version, fetchedAt=fetched, note=note)


def for_file(source: str, path: Path, url: str | None = None, version: str | None = None,
             note: str | None = None) -> Provenance:
    """Provenance of a cached file: fetchedAt = the file's modification time."""
    return provenance(source, file_mtime(path), url=url, version=version, note=note)


def network_provenance(path: Path, version: str | None) -> Provenance:
    return for_file("Primăria Timișoara, rețeaua de transport (SMTT GTFS) / city transit network",
                    path, CITY_TRANSIT_URL, version)


def zones_provenance(path: Path) -> Provenance:
    return for_file("Primăria Timișoara, cartiere / neighbourhoods (/api/zones)", path, CITY_ZONES_URL)


def parking_provenance(path: Path, version: str | None) -> Provenance:
    return for_file("Primăria Timișoara, Timpark (/api/mobile/parking)", path, CITY_PARKING_URL, version)


def gtfs_provenance(path: Path, version: str | None, sha256: str | None = None) -> Provenance:
    note = f"sha256 {sha256[:12]}" if sha256 else None
    return for_file("SMTT GTFS (orar planificat / planned timetable)", path, SMTT_GTFS_URL, version, note)


def vehicles_provenance(recorded_at: datetime, note: str | None = None) -> Provenance:
    return provenance(
        "CityApp vehicule live, înregistrarea noastră / live vehicles, our recording (undocumented API)",
        recorded_at, CITY_VEHICLES_URL, None, note,
    )


def state_provenance(fetched_at: datetime) -> Provenance:
    return provenance("Rețeaua Vie, registrul lucrărilor / closure register", fetched_at, None, None, None)


def from_sources(source_id: str) -> Provenance | None:
    """Provenance of a downloaded source from $DATA_DIR/provenance/sources.json.

    `source_id` is the record id written by backend/scripts/data/fetch_all.sh
    ("osm", "ghsl", ...) or a local file id ("gtfs:<file>", "city-api:<file>").
    Returns None when the file or the record is missing.
    """
    import json

    from app.config import get_settings

    path = get_settings().data_dir / "provenance" / "sources.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    for rec in (data.get("fetched") or []) + (data.get("local") or []):
        if rec.get("id") == source_id:
            return provenance(rec.get("source") or source_id, parse_iso(rec["fetchedAt"]), url=rec.get("url"),
                              version=rec.get("version"), note=rec.get("note"))
    return None
