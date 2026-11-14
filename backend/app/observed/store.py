"""Read L0 (the observed timetable) as built by app.observed.build. Every consumer reads here.

    events()    DataFrame of stop events, every built hour (see build.EVENT_COLUMNS)
    segments()  DataFrame of stop-to-stop runs (build.SEGMENT_COLUMNS)
    reports(stems=None)  the de-duplicated vehicle reports per built hour (build.REPORT_COLUMNS)
    coverage()  {first, last, hours, built, label}: what the numbers are measured on
    label(first, last)  „din N ore înregistrate (vin. 13:47 → sâm. 12:45)”

Times are unix seconds (UTC). Data are re-read when the manifest changes.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.common.timeutil import parse_iso
from app.config import TZ
from app.observed import build

_DAYS_RO = ("lun.", "mar.", "mie.", "joi", "vin.", "sâm.", "dum.")
_DAYS_EN = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

_memo: dict[tuple, pd.DataFrame] = {}


def manifest() -> dict:
    return build.read_manifest()


def built_stems() -> list[str]:
    return sorted(manifest().get("hours", {}))


def _stamp() -> tuple:
    p = build.manifest_path()
    try:
        st = p.stat()
    except OSError:
        return (0, 0)
    return (st.st_mtime_ns, st.st_size)


def _load(kind: str, stems: list[str] | None = None) -> pd.DataFrame:
    stems = built_stems() if stems is None else stems
    key = (kind, tuple(stems), _stamp())
    if key in _memo:
        return _memo[key]
    cols = {"events": build.EVENT_COLUMNS, "segments": build.SEGMENT_COLUMNS, "reports": build.REPORT_COLUMNS}[kind]
    parts = []
    for s in stems:
        p = build.out_dir() / kind / f"{s}.parquet"
        if p.is_file():
            df = pd.read_parquet(p)
            if len(df):
                parts.append(df)
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)
    if len(_memo) > 16:
        _memo.clear()
    _memo[key] = df
    return df


def events() -> pd.DataFrame:
    return _load("events")


def segments() -> pd.DataFrame:
    return _load("segments")


def reports(stems: list[str] | None = None) -> pd.DataFrame:
    return _load("reports", stems)


def _short(dt: datetime, days: tuple[str, ...]) -> str:
    d = dt.astimezone(TZ)
    return f"{days[d.weekday()]} {d:%H:%M}"


def label(first: datetime, last: datetime) -> tuple[str, str]:
    """(ro, en) „din N ore înregistrate (vin. 13:47 → sâm. 12:45)”."""
    hours = max(1, round((last - first).total_seconds() / 3600))
    ro = f"din {hours} ore înregistrate ({_short(first, _DAYS_RO)} → {_short(last, _DAYS_RO)})"
    en = f"from {hours} recorded hours ({_short(first, _DAYS_EN)} → {_short(last, _DAYS_EN)})"
    return ro, en


def coverage() -> dict | None:
    """First and last snapshot of the built hours, their count and the label; None when nothing is built."""
    hours = manifest().get("hours", {})
    firsts = [parse_iso(h["first"]) for h in hours.values() if h.get("first")]
    lasts = [parse_iso(h["last"]) for h in hours.values() if h.get("last")]
    if not firsts:
        return None
    first, last = min(firsts), max(lasts)
    ro, en = label(first, last)
    return {"first": first, "last": last, "built": len(hours), "labelRo": ro, "labelEn": en}
