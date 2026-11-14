"""Disruption history (MMTIS): GET /api/history?from=&to= (SPEC §5.4, §6.7).

Two kinds of rows:
  - closures published through the platform: state/published/<id>.json + the closure's impact;
  - back-filled rows from the STPT notices we recorded ($LIVE_DIR/stpt-posts): every post the M1
    parser reads *cleanly* becomes a row with publishedAt = the post date and the note
    „reconstituit din anunț STPT, nu publicat prin platformă”. Its stops and departures come from
    the same M1 analysis and impact as a closure drawn in the app (not stored as a closure).

A post reads cleanly when the parser finds its window in the text, at least one line action,
every action names its stops (whole-line suspension, kept stops of a shortened line, or the
suspended stops of a diverted line), and every line it names is in the GTFS or is a temporary
line the notice introduces. The other posts are listed in `BackfillSet.unread` with the reason
(`python -m app.m7_compliance.history` prints them).

When a platform-published closure has the same source URL as a back-filled post, the platform row
replaces the reconstructed one.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import datetime

from pydantic import BaseModel

from app.common import state
from app.common.errors import ApiError, invalid
from app.common.stpt_posts import StptPost, load_posts
from app.common.timeutil import iso, local_midnight, parse_iso
from app.m1_disruption.timeline import lead_hours
from app.models.base import I18n, Provenance
from app.models.v2 import HistoryEntry

log = logging.getLogger("reteaua_vie.m7.history")

BACKFILL_VERSION = 2   # bump when the clean-parse rule or the row content changes (2: leadHours, R29/V1 parser)

NOTE_BACKFILLED = I18n(ro="reconstituit din anunț STPT, nu publicat prin platformă",
                       en="reconstructed from an STPT notice, not published through the platform")
NOTE_PLATFORM = I18n(ro="publicat prin platformă", en="published through the platform")


class HistoryRow(HistoryEntry):
    """HistoryEntry + optional fields (CONTRACT HistoryEntry, additive): label, source, provenance."""
    note: I18n | None = None
    sourceUrl: str | None = None
    leadHours: float | None = None   # v2.37 (R15): STPT post → works start, in hours; null = no post known
    provenance: list[Provenance] | None = None


class UnreadPost(BaseModel):
    postId: int
    date: str
    title: str
    reason: str


class BackfillSet(BaseModel):
    entries: list[HistoryRow]
    unread: list[UnreadPost]


# --- reading a post ------------------------------------------------------------------------


def _window_in_text(text: str, ref: datetime) -> bool:
    from app.m1_disruption import parser

    return any(parser.window_from(s, ref) is not None for s in parser.split_sentences(text))


def clean_reasons(post: StptPost, detail) -> list[str]:
    """Why a parsed post is not a clean closure; [] = clean."""
    c = detail.closure
    reasons = []
    if not _window_in_text(post.text, post.date):
        reasons.append("nicio dată sau interval în text / no date or window in the text")
    actions = c.routeActions or []
    if not actions:
        reasons.append("nicio linie cu acțiune recunoscută / no line action recognised")
    for a in actions:
        if a.action == "suspended" and a.fromStopId is None and a.toStopId is None:
            continue
        if a.action == "shortened" and a.keepStopIds:
            continue
        if a.action == "rerouted" and a.suspendedStopIds:
            continue
        what = {"shortened": "stațiile păstrate / kept stops",
                "rerouted": "stațiile suspendate / suspended stops"}.get(a.action, "tronsonul / section")
        reasons.append(f"{a.routeId} sens {a.directionId}: {what} nerecunoscute în text / not resolved")
    temps = {t.shortName.lower() for t in c.temporaryRoutes or []}
    unknown = [t for t in detail.lines_unknown if t.lower() not in temps]
    if unknown:
        reasons.append("linii care nu sunt în GTFS / lines not in the GTFS: " + ", ".join(unknown))
    if detail.served_lists:
        reasons.append("anunțul listează stațiile deservite; cele suspendate cer traseul normal dintr-un GTFS "
                       "mai vechi / the notice lists served stops; suspended ones need an older GTFS pattern")
    return reasons


def _entry_for_post(post: StptPost, detail) -> HistoryRow:
    from app.m1_disruption import analysis as core
    from app.m1_disruption import impact as imp

    closure = detail.closure.model_dump(mode="json")
    closure.update(id=f"stpt_{post.id}", sourceUrl=post.link or None)
    rows = [s.model_dump(mode="json") for s in core.analyze_closure(closure).stops]
    stops = deps = None
    provenance = [post.provenance()]
    try:
        impact = imp.build_impact(closure, rows)
        stops, deps = impact.totals.stopsSuspended, impact.totals.departuresLost
        provenance += impact.provenance
    except ApiError as exc:   # window outside every timetable we hold: unknown, not 0
        provenance.append(Provenance(source="Rețeaua Vie, impact", url=None, version=None,
                                     fetchedAt=iso(post.date), note=exc.message))
    title_en = detail.closure.title.en
    return HistoryRow(
        closureId=closure["id"],
        title=I18n(ro=post.title, en=title_en),
        window=closure["window"],
        publishedAt=iso(post.date),
        alertsCount=None,
        stopsSuspended=stops,
        departuresLost=deps,
        routeIds=list(closure.get("routeIds") or []),
        note=NOTE_BACKFILLED,
        sourceUrl=post.link or None,
        provenance=provenance,
        leadHours=lead_hours(post.date, closure["window"]["start"]),
    )


def build_backfill() -> BackfillSet:
    from app.m1_disruption import parser

    entries, unread = [], []
    for pid, post in sorted(load_posts().items()):
        try:
            detail = parser.parse_detail(post.text, post.date)
            reasons = clean_reasons(post, detail)
            if not reasons:
                entries.append(_entry_for_post(post, detail))
                continue
        except Exception as exc:   # noqa: BLE001 - one bad post never hides the others
            log.exception("back-fill of STPT post %s failed", pid)
            reasons = [f"eroare la citire / read error: {type(exc).__name__}"]
        unread.append(UnreadPost(postId=pid, date=iso(post.date), title=post.title, reason="; ".join(reasons)))
    return BackfillSet(entries=entries, unread=unread)


def backfill_key() -> str:
    """Job-cache key: the recorded posts, the timetable and this module's rule version."""
    from app.common import gtfs

    posts = sorted((pid, p.path.name) for pid, p in load_posts().items())
    blob = json.dumps([BACKFILL_VERSION, posts, gtfs.feed().sha256], sort_keys=True)
    return "m7:history-backfill:" + hashlib.sha256(blob.encode()).hexdigest()[:16]


def backfill() -> BackfillSet:
    """The back-filled rows, from the job cache when the posts and timetable did not change."""
    from app.common.jobs import compute_and_cache

    return compute_and_cache(backfill_key(), build_backfill)


# --- platform rows -----------------------------------------------------------------------------


def _lead(closure: dict) -> float | None:
    from app.m1_disruption.timeline import post_for

    post = post_for(closure)
    return lead_hours(post.date, closure["window"]["start"]) if post else None


def platform_rows() -> list[HistoryRow]:
    out = []
    for pub in state.list_all("published"):
        cid = pub.get("closureId")
        closure = state.read("closures", cid) if cid else None
        if closure is None:
            continue
        impact = state.read("closures", cid, state.PART_IMPACT)
        if impact is None:
            try:
                from app.m1_disruption.impact import compute_impact

                impact = compute_impact(cid).model_dump(mode="json")
            except ApiError:
                impact = None
        totals = (impact or {}).get("totals") or {}
        out.append(HistoryRow(
            closureId=cid,
            title=closure["title"],
            window=closure["window"],
            publishedAt=pub["publishedAt"],
            alertsCount=len(pub.get("alerts") or []),
            stopsSuspended=totals.get("stopsSuspended"),
            departuresLost=totals.get("departuresLost"),
            routeIds=list(closure.get("routeIds") or sorted({a["informedEntity"][0]["routeId"]
                                                               for a in pub.get("alerts") or []
                                                               if a.get("informedEntity")})),
            note=(I18n.model_validate(pub["reconstructedNote"]) if pub.get("reconstructed")
                  and pub.get("reconstructedNote") else NOTE_PLATFORM),
            sourceUrl=closure.get("sourceUrl"),
            provenance=(impact or {}).get("provenance") or None,
            leadHours=_lead(closure),
        ))
    return out


# --- the endpoint ------------------------------------------------------------------------------


def parse_bound(value: str | None, end: bool = False) -> datetime | None:
    """`from` / `to`: an ISO date (whole day) or an ISO time with or without offset."""
    if not value:
        return None
    try:
        if len(value) == 10:
            day = datetime.strptime(value, "%Y-%m-%d").date()
            start = local_midnight(day)
            return local_midnight(day.fromordinal(day.toordinal() + 1)) if end else start
        return parse_iso(value)
    except ValueError:
        raise invalid(f"Not an ISO date or time: {value!r}.") from None


def history(date_from: str | None = None, date_to: str | None = None) -> list[HistoryRow]:
    """Rows whose window overlaps [from, to], newest publication first."""
    lo, hi = parse_bound(date_from), parse_bound(date_to, end=True)
    if lo and hi and hi <= lo:
        raise invalid("`to` must be after `from`.")
    platform = platform_rows()
    replaced = {r.sourceUrl for r in platform if r.sourceUrl}
    rows = platform + [r for r in backfill().entries if r.sourceUrl not in replaced]

    def overlaps(r: HistoryRow) -> bool:
        s, e = parse_iso(r.window.start), parse_iso(r.window.end)
        return (lo is None or e > lo) and (hi is None or s < hi)

    return sorted((r for r in rows if overlaps(r)), key=lambda r: parse_iso(r.publishedAt), reverse=True)


if __name__ == "__main__":   # print what the back-fill read and what it left unread
    bf = build_backfill()
    for r in bf.entries:
        print(f"READ   {r.closureId}  {r.publishedAt}  {r.window.start} -> {r.window.end}  routes={r.routeIds}  "
              f"stopsSuspended={r.stopsSuspended}  departuresLost={r.departuresLost}")
    for u in bf.unread:
        print(f"UNREAD {u.postId}  {u.date[:10]}  {u.title[:70]!r}\n       {u.reason}")
    sys.exit(0)
