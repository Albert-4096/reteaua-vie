"""Spillover (Braess F2, SPEC §6.4, CONTRACT DetourLoad.spillover): measured, not modelled.

Mean `delaySec` of the recorded vehicles on the detour-load top edges vs. the rest of the
network, over the same hours: the recorded hours that fall inside the closure window. Only a
closure whose window overlaps our vehicle recording gets a value (of the prepared cases, only
Mocioni, which runs during the recording); every other closure gets `null`.

One observation = one vehicle report, de-duplicated by (vehicle, updatedAt) so a vehicle whose
report did not change between two 15 s polls counts once. A report is "on the edges" when its
position is within 20 m of a top edge.

Label: „comparație cu restul rețelei, nu efectul închiderii” (the edges may be slower for
reasons that have nothing to do with the closure).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta, timezone
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString

from app.common import provenance as prov
from app.common import vehicles
from app.common.geo import project_lonlats, to_metric
from app.common.timeutil import from_unix, iso, parse_iso
from app.config import get_settings
from app.models.base import I18n
from app.models.v2 import DetourLoad, Spillover

log = logging.getLogger(__name__)

NEAR_EDGE_M = 20.0

LABEL = I18n(
    ro="Comparație cu restul rețelei, nu efectul închiderii. Întârzieri înregistrate de vehiculele STPT.",
    en="Comparison with the rest of the network, not the effect of the closure. Delays recorded by STPT vehicles.",
)


def _obs_cache(path: Path) -> Path:
    st = path.stat()
    key = hashlib.sha1(f"{path.name}:{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()[:12]
    return get_settings().cache_dir / "vehicle_obs" / f"{path.name[:-len('.jsonl.gz')]}_{key}.npz"


def file_observations(path: Path) -> dict[str, np.ndarray]:
    """One recording file -> arrays t (unix s of the poll), x, y (UTM metres), delay (s), unique."""
    cache = _obs_cache(path)
    if cache.is_file():
        try:
            return dict(np.load(cache))
        except Exception:
            pass
    seen: set[tuple[str, int]] = set()
    t, lonlat, delay = [], [], []
    for snap in vehicles.read_file(path):
        ts = vehicles.snapshot_time(snap).timestamp()
        for v in snap.get("vehicles") or []:
            if v.get("lat") is None or v.get("lon") is None or v.get("delaySec") is None:
                continue
            key = (str(v.get("id")), int(v.get("updatedAt") or ts))
            if key in seen:
                continue
            seen.add(key)
            t.append(ts)
            lonlat.append((float(v["lon"]), float(v["lat"])))
            delay.append(float(v["delaySec"]))
    xy = project_lonlats(lonlat)
    out = {"t": np.asarray(t, dtype=float), "x": xy[:, 0] if len(xy) else np.zeros(0),
           "y": xy[:, 1] if len(xy) else np.zeros(0), "delay": np.asarray(delay, dtype=float)}
    # the newest file is still being written: cache only closed hours
    if path != vehicles.recording_files()[-1][0]:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_name(cache.stem + ".tmp.npz")
        np.savez_compressed(tmp, **out)
        tmp.replace(cache)
    return out


def _window_obs(closure: dict) -> tuple[np.ndarray, ...] | None:
    """(t, x, y, delay) of the recorded reports inside the closure window, or None."""
    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    s_utc, e_utc = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    files = [p for p, h in vehicles.recording_files() if h + timedelta(hours=1) > s_utc and h < e_utc]
    if not files:
        return None
    parts = [file_observations(p) for p in files]
    t = np.concatenate([p["t"] for p in parts])
    keep = (t >= start.timestamp()) & (t < end.timestamp())
    if not keep.any():
        return None
    return (t[keep], np.concatenate([p["x"] for p in parts])[keep],
            np.concatenate([p["y"] for p in parts])[keep], np.concatenate([p["delay"] for p in parts])[keep])


def _on_edges(edge_lines: list[LineString], x: np.ndarray, y: np.ndarray) -> np.ndarray:
    zone = shapely.union_all([to_metric(line) for line in edge_lines]).buffer(NEAR_EDGE_M)
    shapely.prepare(zone)
    return shapely.contains_xy(zone, x, y)


def compute_spillover(closure: dict, edge_lines: list[LineString]) -> tuple[Spillover | None, dict | None]:
    """F2 for one closure from its detour-load top edges (WGS84).

    Returns (spillover, {"onEdges": n, "network": m}); (None, None) without a recording.
    """
    obs = _window_obs(closure) if edge_lines else None
    if obs is None:
        return None, None
    t, x, y, delay = obs
    on = _on_edges(edge_lines, x, y)
    n = {"onEdges": int(on.sum()), "network": int((~on).sum())}
    if not on.any() or on.all():
        return None, n
    hours = round((float(t.max()) - float(t.min())) / 3600.0, 1)
    return Spillover(
        meanDelaySecOnEdges=round(float(delay[on].mean()), 1),
        meanDelaySecNetwork=round(float(delay[~on].mean()), 1),
        hours=hours,
        **{"from": iso(from_unix(float(t.min())))},
        to=iso(from_unix(float(t.max()))),
        label=LABEL,
    ), n


_memo: dict[tuple, tuple[Spillover | None, dict | None]] = {}


def _recording_stamp() -> tuple:
    files = vehicles.recording_files()
    if not files:
        return ()
    last = files[-1][0].stat()
    return (len(files), files[-1][0].name, last.st_size)


def with_spillover(closure: dict, result: DetourLoad) -> DetourLoad:
    """`result` with its spillover from the recording as it is now (memoised per recording state)."""
    lines = [LineString(e.geometry.coordinates) for e in result.edges]
    key = (closure.get("id"), closure["window"]["start"], closure["window"]["end"],
           tuple(tuple(map(tuple, e.geometry.coordinates)) for e in result.edges), _recording_stamp())
    if key not in _memo:
        if len(_memo) > 64:
            _memo.clear()
        _memo[key] = compute_spillover(closure, lines)
    spill, n = _memo[key]
    if spill is None:
        return result.model_copy(update={"spillover": None})
    note = (f"Înregistrare reală, {spill.from_} – {spill.to}; {n['onEdges']} rapoarte pe străzile de ocolire, "
            f"{n['network']} în restul rețelei / real recording; reports on the detour streets vs. the rest")
    return result.model_copy(update={
        "spillover": spill,
        "provenance": [*result.provenance, prov.vehicles_provenance(parse_iso(spill.to), note)],
    })
