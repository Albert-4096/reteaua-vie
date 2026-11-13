"""Level of Traffic Stress (LTS) for one OSM way (SPEC §6.5).

The table (SPEC §6.5, as printed in the README):

| LTS | Way |
|---|---|
| 1 | `highway=cycleway`, or `cycleway=track`, or `highway=path` with `bicycle=designated` |
| 2 | `cycleway=lane` on a road with maxspeed ≤ 30, or a residential street ≤ 30 with no lane |
| 3 | a lane on a road with maxspeed ≤ 50 |
| 4 | a road with maxspeed > 50, or `primary` / `trunk` with no facility |
| null | maxspeed missing: the urban default 50 is used, unless the highway class is unknown: then `null` („necunoscut”) |

Cases the table leaves open, decided here (marked * in the README):

| LTS | Way |
|---|---|
| 1* | `footway` / `pedestrian` with `bicycle=designated` (Timișoara maps most sidewalk bike paths this way) |
| 2* | `path` / `footway` / `pedestrian` / `track` / `bridleway` with `bicycle=yes` or `permissive`, and `path` with no bicycle tag (no motor traffic, shared with people walking) |
| 2 / 3* | `residential`, `living_street`, `service`, `unclassified` with no lane: 2 at ≤ 30, else 3; `living_street` without maxspeed counts as 20 |
| 3* | `tertiary` / `secondary` (and links) ≤ 50 with no lane |
| — | `footway` / `pedestrian` without a bicycle permission, `bicycle=no`, `motorway`: not part of the bike network |

Any side counts: `cycleway`, `cycleway:left`, `cycleway:right`, `cycleway:both`. `lane` and
`opposite_lane` are lanes; `track` and `opposite_track` are tracks; `shared_lane` (a painted
symbol in the traffic lane) is no facility. maxspeed `RO:urban` = 50, `RO:rural` = 90,
`RO:motorway` = 130, `walk` = 5.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Mapping

Lts = Literal[1, 2, 3, 4]

URBAN_DEFAULT = 50
SIDE_KEYS = ("cycleway", "cycleway:left", "cycleway:right", "cycleway:both")
LANE_VALUES = {"lane", "opposite_lane"}
TRACK_VALUES = {"track", "opposite_track"}
PATH_CLASSES = {"path", "footway", "pedestrian", "track", "bridleway"}
LOCAL_CLASSES = {"residential", "living_street", "service", "unclassified"}
MAIN_CLASSES = {"tertiary", "tertiary_link", "secondary", "secondary_link"}
BIG_CLASSES = {"primary", "primary_link", "trunk", "trunk_link"}
ROAD_CLASSES = LOCAL_CLASSES | MAIN_CLASSES | BIG_CLASSES
SPEED_WORDS = {"ro:urban": 50, "ro:rural": 90, "ro:motorway": 130, "ro:living_street": 20, "walk": 5}
BIKE_OK = {"designated", "yes", "permissive"}


def _s(tags: Mapping[str, Any], key: str) -> str:
    v = tags.get(key)
    return v.strip().lower() if isinstance(v, str) else ""


def maxspeed(tags: Mapping[str, Any]) -> int | None:
    """The tagged maxspeed in km/h, or None when missing or unreadable."""
    raw = _s(tags, "maxspeed")
    if not raw:
        return None
    if raw in SPEED_WORDS:
        return SPEED_WORDS[raw]
    m = re.match(r"^(\d+)(\s*mph)?", raw)
    if not m:
        return None
    v = int(m.group(1))
    return round(v * 1.609) if m.group(2) else v


def facility(tags: Mapping[str, Any]) -> Literal["track", "lane", None]:
    values = {_s(tags, k) for k in SIDE_KEYS}
    if values & TRACK_VALUES:
        return "track"
    if values & LANE_VALUES:
        return "lane"
    return None


def in_network(tags: Mapping[str, Any]) -> bool:
    """Whether a cyclist may ride on the way at all."""
    hw = _s(tags, "highway")
    bike = _s(tags, "bicycle")
    if bike == "no" or hw in ("motorway", "motorway_link", "steps", "construction", "proposed"):
        return False
    if hw in ("footway", "pedestrian"):
        return bike in BIKE_OK
    return bool(hw)


def lts(tags: Mapping[str, Any]) -> Lts | None:
    """LTS 1-4 of a way from its OSM tags, or None (unknown class / not in the bike network)."""
    if not in_network(tags):
        return None
    hw = _s(tags, "highway")
    bike = _s(tags, "bicycle")
    fac = facility(tags)
    if hw == "cycleway" or fac == "track":
        return 1
    if hw in PATH_CLASSES:
        if bike == "designated" and hw in ("path", "footway", "pedestrian"):
            return 1
        if bike in ("yes", "permissive") or (hw == "path" and not bike):
            return 2
        return None  # a track with no bicycle tag: unknown
    if hw not in ROAD_CLASSES:
        return None
    speed = maxspeed(tags)
    if speed is None:
        speed = 20 if hw == "living_street" else URBAN_DEFAULT
    if speed > 50:
        return 4
    if fac == "lane":
        return 2 if speed <= 30 else 3
    if hw in BIG_CLASSES:
        return 4
    if hw in LOCAL_CLASSES and speed <= 30:
        return 2
    return 3


def is_bike_way(tags: Mapping[str, Any]) -> bool:
    """Bike infrastructure (the 'lane' features): a cycleway, a track, a designated path, or a lane."""
    if not in_network(tags):
        return False
    hw = _s(tags, "highway")
    if hw == "cycleway" or facility(tags) is not None:
        return True
    return hw in ("path", "footway", "pedestrian") and _s(tags, "bicycle") == "designated"
