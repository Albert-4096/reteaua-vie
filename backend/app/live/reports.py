"""Sesizări around a closure (SPEC §6.9): counts only, never the reports themselves.

Source: our recording of sesizari.primariatm.ro/api/sesizari in
$LIVE_DIR/sesizari/YYYYMMDD-HHMM.json (UTC time of the poll). Each poll asks
for the reports of the last 2 days, so the files overlap: rows are
de-duplicated by `id`, the newest poll wins (its status is the latest).

Counted: reports within `radius` metres of the closure (its geometry, else its
affected stops), created from the window start minus 7 days to the window end.
Returned: the count per `categorii.nume` and how many are resolved. Text,
photos, names and points never leave this module (GDPR). The recording covers
only the days it polled; outside them the total is null ("necunoscut"), never 0.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from shapely.geometry import MultiPoint, Point

from app.common import state
from app.common import provenance as prov
from app.common.errors import invalid, not_found
from app.common.geo import from_geojson, to_metric
from app.common.timeutil import iso, local_midnight, parse_iso
from app.config import TZ, get_settings

SESIZARI_URL = "https://sesizari.primariatm.ro/api/sesizari"
POLL_DAYS_BACK = 2          # the recorder asks for startDate = poll day - 2 days
DAYS_BEFORE = 7             # SPEC §6.9: window start minus 7 days
RESOLVED = frozenset({"Finalizata"})   # the only status that means the problem was fixed
MAX_RADIUS = 5000.0


@dataclass(frozen=True)
class Report:
    """The fields we keep in memory; nothing personal is kept or returned."""
    id: str
    created: datetime
    category: str
    status: str
    x: float     # metric (UTM 34N), for the distance test only
    y: float
    sub: str = ""   # `subcategorii.nume` (e.g. „Groapă”); a label, never the report text


def sesizari_dir() -> Path:
    return get_settings().live_dir / "sesizari"


def _poll_files() -> list[tuple[Path, datetime]]:
    d = sesizari_dir()
    out = []
    for p in d.glob("*.json") if d.is_dir() else []:
        try:
            t = datetime.strptime(p.stem, "%Y%m%d-%H%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        out.append((p, t))
    out.sort(key=lambda x: x[1])
    return out


def _signature() -> tuple:
    return tuple((str(p), p.stat().st_size, p.stat().st_mtime) for p, _ in _poll_files())


@lru_cache(maxsize=2)
def _load(signature: tuple) -> dict[str, Report]:
    """{id: Report} de-duplicated by id; the newest poll wins."""
    reports: dict[str, Report] = {}
    for path_str, _size, _mtime in signature:
        try:
            rows = json.loads(Path(path_str).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # a poll being written or broken: skip it
        for r in rows if isinstance(rows, list) else []:
            try:
                lon, lat = (r.get("locatie") or {}).get("coordinates")[:2]
                created = parse_iso(r["createdAt"])
                pt = to_metric(Point(float(lon), float(lat)))
            except (TypeError, ValueError, KeyError):
                continue
            rid = str(r.get("id"))
            reports[rid] = Report(id=rid, created=created,
                                  category=((r.get("categorii") or {}).get("nume") or "necunoscută").strip(),
                                  status=str(r.get("status") or ""), x=pt.x, y=pt.y,
                                  sub=((r.get("subcategorii") or {}).get("nume") or "").strip())
    return reports


def load_reports() -> dict[str, Report]:
    return _load(_signature())


def status_values() -> list[str]:
    """The distinct `status` values in the recording (for the test and the docs)."""
    return sorted({r.status for r in load_reports().values()})


def coverage() -> tuple[datetime, datetime] | None:
    """(from, to) of the creation times our polls cover: first poll's start day to the last poll."""
    files = _poll_files()
    if not files:
        return None
    first = files[0][1].astimezone(TZ).date() - timedelta(days=POLL_DAYS_BACK)
    return local_midnight(first), files[-1][1].astimezone(TZ)


def closure_area(closure: dict, analysis: dict | None):
    """Metric geometry the radius is measured from: the closure line, else its affected stops."""
    geom = closure.get("geometry")
    if geom:
        try:
            return to_metric(from_geojson(geom))
        except Exception:  # noqa: BLE001 - fall back to the stops
            pass
    pts = [s["location"] for s in (analysis or {}).get("stops") or [] if s.get("location")]
    if pts:
        return to_metric(MultiPoint([(p[0], p[1]) for p in pts]))
    return None


def report_summary(closure_id: str, radius: float = 500.0, since: datetime | None = None) -> dict:
    """ReportSummary (CONTRACT, + v2.3 optional coveredFrom/coveredTo/note).

    `since` (R20) counts only reports created at or after that moment, up to the
    window end. The board passes the closure's publishedAt. Counts and categories
    only: no report text, photo, name or point.
    """
    if not (0 < radius <= MAX_RADIUS):
        raise invalid(f"`radius` must be between 1 and {int(MAX_RADIUS)} metres")
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id!r}.")
    analysis = state.read("closures", closure_id, state.PART_ANALYSIS)
    start = parse_iso(closure["window"]["start"]) - timedelta(days=DAYS_BEFORE)
    end = parse_iso(closure["window"]["end"])
    if since is not None:
        if since.tzinfo is None:
            raise invalid("`since` must be an ISO 8601 time with an offset")
        if since >= end:
            raise invalid("`since` must be before the closure window ends")
        start = since
    cov = coverage()
    files = _poll_files()
    fetched = files[-1][1] if files else datetime.now(timezone.utc)
    base = {"closureId": closure_id, "radiusMeters": float(radius), "from": iso(start), "to": iso(end),
            "coveredFrom": None, "coveredTo": None}

    def provenance(note: str) -> list[dict]:
        return [prov.provenance("Primăria Timișoara, sesizări publice (înregistrarea noastră) / public reports, "
                                "our recording", fetched, SESIZARI_URL, None, note).model_dump()]

    area = closure_area(closure, analysis)
    if cov is None or end <= cov[0] or start >= cov[1] or area is None:
        why_ro = ("lucrarea nu are geometrie sau stații" if area is None and cov is not None
                  else f"înregistrarea noastră acoperă {iso(cov[0])} – {iso(cov[1])}" if cov
                  else "nu există înregistrare")
        why_en = ("the closure has no geometry or stops" if area is None and cov is not None
                  else f"our recording covers {iso(cov[0])} – {iso(cov[1])}" if cov else "no recording")
        note = {"ro": f"Sesizările din perioada {iso(start)} – {iso(end)} sunt necunoscute: {why_ro}.",
                "en": f"Reports for {iso(start)} – {iso(end)} are unknown: {why_en}."}
        return {**base, "total": None, "byCategory": [], "note": note, "provenance": provenance(note["en"])}

    lo, hi = max(start, cov[0]), min(end, cov[1])
    zone = area.buffer(radius)
    by_cat: dict[str, list[int]] = {}
    for r in load_reports().values():
        if not (lo <= r.created < hi):
            continue
        if not zone.contains(Point(r.x, r.y)):
            continue
        c = by_cat.setdefault(r.category, [0, 0])
        c[0] += 1
        c[1] += r.status in RESOLVED
    rows = sorted(({"category": k, "count": v[0], "resolved": v[1]} for k, v in by_cat.items()),
                  key=lambda x: (-x["count"], x["category"]))
    partial = lo > start or hi < end
    note_ro = (f"Sesizări create între {iso(lo)} și {iso(hi)}, la cel mult {int(radius)} m de lucrare. "
               f"Rezolvate = status „Finalizata”. Doar numărul pe categorii: fără text, fotografii, nume sau puncte.")
    note_en = (f"Reports created between {iso(lo)} and {iso(hi)}, within {int(radius)} m of the closure. "
               f"Resolved = status 'Finalizata'. Counts per category only: no text, photos, names or points.")
    if partial:
        note_ro += (f" Atenție: înregistrarea noastră acoperă doar {iso(lo)} – {iso(hi)} din perioada cerută "
                    f"{iso(start)} – {iso(end)}.")
        note_en += f" Note: our recording covers only {iso(lo)} – {iso(hi)} of {iso(start)} – {iso(end)}."
    return {**base, "coveredFrom": iso(lo), "coveredTo": iso(hi), "total": sum(x["count"] for x in rows),
            "byCategory": rows, "note": {"ro": note_ro, "en": note_en}, "provenance": provenance(note_en)}
