"""GTFS-RT service alerts for published closures (SPEC §6.1 items 11 and 12).

One Alert per affected stop (its informed entities are the (route, stop,
direction) rows suspended there) plus one route-level Alert per line that a
closure suspends as a whole. Per-stop alerts are what the stop poster, the QR
page (`/a/{closureId}?stop={stopId}`) and the audio need: each one has its own
text, effect and URL.

Texts are RO + EN from templates/alert_texts.json. The tts_ texts spell every
number as words and expand abbreviations, so a speech engine reads them right.

The feed is a FULL_DATASET FeedMessage (gtfs-realtime 2.0). `validate_feed`
runs the MobilityData gtfs-realtime-validator jar from $DATA_DIR/tools/ and
falls back to an internal protobuf check ("verificare internă").
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal

from google.transit import gtfs_realtime_pb2 as rt

from app import config
from app.cases.catalog import CASES_BY_CLOSURE
from app.common import gtfs
from app.common import provenance as prov
from app.common.city import load_network
from app.common.timeutil import iso, parse_iso
from app.config import TZ, real_now
from app.m1_disruption.impact import counts_as_lost
from app.models.base import I18n, Model, Provenance
from app.models.v1 import Alert, InformedEntity

TEMPLATES = Path(__file__).resolve().parent / "templates"


@lru_cache(maxsize=1)
def texts() -> dict:
    return json.loads((TEMPLATES / "alert_texts.json").read_text(encoding="utf-8"))


# --- numbers as words -------------------------------------------------------------

_RO_UNITS = ["zero", "unu", "doi", "trei", "patru", "cinci", "șase", "șapte", "opt", "nouă"]
_RO_TEENS = ["zece", "unsprezece", "doisprezece", "treisprezece", "paisprezece", "cincisprezece",
             "șaisprezece", "șaptesprezece", "optsprezece", "nouăsprezece"]
_RO_TENS = {2: "douăzeci", 3: "treizeci", 4: "patruzeci", 5: "cincizeci", 6: "șaizeci",
            7: "șaptezeci", 8: "optzeci", 9: "nouăzeci"}


def ro_words(n: int, feminine: bool = False) -> str:
    """Romanian cardinal in words (0 .. 999 999). feminine: 2 -> două, 12 -> douăsprezece."""
    if n < 0:
        return "minus " + ro_words(-n, feminine)
    if n < 10:
        return "două" if feminine and n == 2 else _RO_UNITS[n]
    if n < 20:
        return "douăsprezece" if feminine and n == 12 else _RO_TEENS[n - 10]
    if n < 100:
        tens, unit = divmod(n, 10)
        return _RO_TENS[tens] + (f" și {ro_words(unit, feminine)}" if unit else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        head = "o sută" if hundreds == 1 else f"{ro_words(hundreds, True)} sute"
        return head + (f" {ro_words(rest, feminine)}" if rest else "")
    if n < 1_000_000:
        thousands, rest = divmod(n, 1000)
        if thousands == 1:
            head = "o mie"
        else:
            words = ro_words(thousands, True)
            if words.endswith(" și unu"):
                words = words[:-3] + "una"  # 21 000 = douăzeci și una de mii
            head = words + (" de mii" if _ro_needs_de(thousands) else " mii")
        return head + (f" {ro_words(rest, feminine)}" if rest else "")
    return str(n)


def _ro_needs_de(n: int) -> bool:
    """Romanian puts „de” between a number and its noun from 20 on (20 de metri, 101 metri)."""
    return n >= 20 and (n % 100 == 0 or n % 100 >= 20)


def ro_count(n: int, singular: str, plural: str, feminine: bool = False) -> str:
    if n == 1:
        return f"{'o' if feminine else 'un'} {singular}"
    return f"{ro_words(n, feminine)} {'de ' if _ro_needs_de(n) else ''}{plural}"


_EN_SMALL = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
             "fourteen fifteen sixteen seventeen eighteen nineteen").split()
_EN_TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty", 6: "sixty", 7: "seventy",
            8: "eighty", 9: "ninety"}


def en_words(n: int) -> str:
    """English cardinal in words (0 .. 999 999)."""
    if n < 0:
        return "minus " + en_words(-n)
    if n < 20:
        return _EN_SMALL[n]
    if n < 100:
        tens, unit = divmod(n, 10)
        return _EN_TENS[tens] + (f"-{_EN_SMALL[unit]}" if unit else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{_EN_SMALL[hundreds]} hundred" + (f" and {en_words(rest)}" if rest else "")
    if n < 1_000_000:
        thousands, rest = divmod(n, 1000)
        head = f"{en_words(thousands)} thousand"
        if not rest:
            return head
        return head + (" and " if rest < 100 else " ") + en_words(rest)
    return str(n)


def en_year_or_number(n: int) -> str:
    """1989 -> nineteen eighty-nine; other numbers as cardinals."""
    if 1100 <= n <= 2099 and not 2000 <= n <= 2009 and n % 100:
        hi, lo = divmod(n, 100)
        return f"{en_words(hi)} {en_words(lo) if lo >= 10 else 'oh ' + en_words(lo)}"
    return en_words(n)


_EN_ORDINAL_IRREGULAR = {"one": "first", "two": "second", "three": "third", "five": "fifth",
                         "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}


def en_ordinal(n: int) -> str:
    words = en_words(n)
    head, sep, last = words.rpartition("-") if "-" in words else words.rpartition(" ")
    if last in _EN_ORDINAL_IRREGULAR:
        last = _EN_ORDINAL_IRREGULAR[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    else:
        last += "th"
    return f"{head}{sep}{last}"


# --- speakable text ---------------------------------------------------------------

# Abbreviations found in the city's stop names and in notice titles.
_RO_ABBREVIATIONS = [
    (r"\bSf\.\s*Apostoli\b", "Sfinții Apostoli"),
    (r"\bBd\.\s*", "Bulevardul "),
    (r"\bB-dul\b\.?\s*", "Bulevardul "),
    (r"\bStr\.\s*", "Strada "),
    (r"\bstr\.\s*", "strada "),
    (r"\bCal\.\s*", "Calea "),
    (r"\bP-ța\b\.?\s*", "Piața "),
    (r"\b[Nn]r\.\s*", "numărul "),
    (r"\bSf\.\s*", "Sfântul "),
    (r"\bJud\.\s*", "Județeană "),
    (r"\bind\.\s*", "industrial "),
    (r"\bFac\.\s*", "Facultatea "),
    (r"\bDr\.\s*", "Doctor "),
    (r"\bDN\s*(?=\d)", "drumul național "),
]
_EN_ABBREVIATIONS = [
    (r"\bBlvd\b\.?", "Boulevard"),
    (r"\bSt\b\.?", "Street"),
    (r"\bSq\b\.?", "Square"),
    (r"\bAve\b\.?", "Avenue"),
]


def _tidy(text: str) -> str:
    text = text.replace("(", ", ").replace(")", "")
    text = re.sub(r"\s+[–—-]\s+", ", ", text)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r",\s*\.", ".", text)
    text = re.sub(r"(?<=[A-Za-zĂÂÎȘȚăâîșț])(?=\d)|(?<=\d)(?=[A-Za-zĂÂÎȘȚăâîșț])", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def speak_ro(text: str) -> str:
    """Romanian text for a speech engine: abbreviations expanded, numbers as words."""
    for pattern, repl in _RO_ABBREVIATIONS:
        text = re.sub(pattern, repl, text)
    text = _tidy(text)
    text = re.sub(r"(\d+)\s*km\b", lambda m: ro_count(int(m.group(1)), "kilometru", "kilometri"), text)
    text = re.sub(r"(\d+)\s*m\b", lambda m: ro_count(int(m.group(1)), "metru", "metri"), text)
    text = re.sub(r"\d+", lambda m: ro_words(int(m.group(0))), text)
    return re.sub(r"\s{2,}", " ", text).strip()


def speak_en(text: str) -> str:
    """English text for a speech engine (Romanian names keep Romanian words)."""
    for pattern, repl in _RO_ABBREVIATIONS + _EN_ABBREVIATIONS:
        text = re.sub(pattern, repl, text)
    text = _tidy(text)
    text = re.sub(r"(\d+)\s*km\b", lambda m: f"{en_words(int(m.group(1)))} kilometres", text)
    text = re.sub(r"(\d+)\s*m\b", lambda m: f"{en_words(int(m.group(1)))} metres", text)
    text = re.sub(r"\d+", lambda m: en_year_or_number(int(m.group(0))), text)
    return re.sub(r"\s{2,}", " ", text).strip()


# --- dates and windows ------------------------------------------------------------

RO_MONTHS = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august",
             "septembrie", "octombrie", "noiembrie", "decembrie"]
EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]


def _end_parts(end: datetime) -> tuple[datetime, int, int]:
    """An end at 00:00 is shown as 24:00 of the day before (as STPT writes it)."""
    if end.hour == 0 and end.minute == 0:
        return end - timedelta(days=1), 24, 0
    return end, end.hour, end.minute


def window_text(start: datetime, end: datetime, lang: str, open_end: bool = False) -> str:
    """'8 noiembrie 2026, 10:00–18:00' / '8 November 2026, 10:00–18:00'."""
    s, e = start.astimezone(TZ), end.astimezone(TZ)
    months = RO_MONTHS if lang == "ro" else EN_MONTHS
    sday = f"{s.day} {months[s.month - 1]} {s.year}"
    stime = f"{s.hour:02d}:{s.minute:02d}"
    if open_end:
        if lang == "ro":
            return f"din {sday}, {stime}, până la finalizarea lucrărilor"
        return f"from {sday}, {stime}, until the works end"
    eday_dt, eh, em = _end_parts(e)
    etime = f"{eh:02d}:{em:02d}"
    if eday_dt.date() == s.date():
        return f"{sday}, {stime}–{etime}"
    eday = f"{eday_dt.day} {months[eday_dt.month - 1]} {eday_dt.year}"
    return f"{sday}, {stime} – {eday}, {etime}"


def _ro_clock(hour: int, minute: int) -> str:
    if hour in (0, 24) and minute == 0:
        return "miezul nopții"
    words = f"ora {ro_words(hour % 24, feminine=True)}"
    return words + (f" și {ro_words(minute)}" if minute else "")


def _en_clock(hour: int, minute: int) -> str:
    if hour in (0, 24) and minute == 0:
        return "midnight"
    if hour == 12 and minute == 0:
        return "noon"
    h12 = hour % 12 or 12
    words = en_words(h12)
    if minute:
        words += f" {en_words(minute) if minute >= 10 else 'oh ' + en_words(minute)}"
    part = "in the morning" if hour < 12 else "in the afternoon" if hour < 18 else "in the evening"
    return f"{words} {part}"


def _ro_date(d: datetime) -> str:
    day = "întâi" if d.day == 1 else ro_words(d.day)
    return f"{day} {RO_MONTHS[d.month - 1]}"


def _en_date(d: datetime) -> str:
    return f"the {en_ordinal(d.day)} of {EN_MONTHS[d.month - 1]}"


def window_tts(start: datetime, end: datetime, lang: str, open_end: bool = False) -> str:
    s, e = start.astimezone(TZ), end.astimezone(TZ)
    eday, eh, em = _end_parts(e)
    if lang == "ro":
        if open_end:
            return f"Începând cu {_ro_date(s)}, până la finalizarea lucrărilor"
        if eday.date() == s.date():
            return f"Pe {_ro_date(s)}, între {_ro_clock(s.hour, s.minute)} și {_ro_clock(eh, em)}"
        end_clock = "la miezul nopții" if eh == 24 else _ro_clock(eh, em)
        return f"Din {_ro_date(s)}, {_ro_clock(s.hour, s.minute)}, până pe {_ro_date(eday)}, {end_clock}"
    if open_end:
        return f"From {_en_date(s)} until the works end"
    if eday.date() == s.date():
        return f"On {_en_date(s)}, from {_en_clock(s.hour, s.minute)} until {_en_clock(eh, em)}"
    return (f"From {_en_clock(s.hour, s.minute)} on {_en_date(s)} "
            f"until {_en_clock(eh, em)} on {_en_date(eday)}")


# --- lines -----------------------------------------------------------------------


def _line_key(short: str) -> tuple:
    m = re.match(r"([A-Za-z]*)(\d*)(.*)", short)
    letters, digits, rest = m.groups() if m else (short, "", "")
    return (letters, int(digits) if digits else -1, rest)


def lines_phrase(shorts: list[str], lang: str, spoken: bool = False) -> str:
    """['4', '7'] -> 'liniile 4 și 7' / 'lines 4 and 7' (spoken: 'liniile patru și șapte')."""
    names = sorted(dict.fromkeys(shorts), key=_line_key)
    if spoken:
        names = [speak_ro(n) if lang == "ro" else speak_en(n) for n in names]
    if lang == "ro":
        word, conj = ("linia", "și") if len(names) == 1 else ("liniile", "și")
    else:
        word, conj = ("line", "and") if len(names) == 1 else ("lines", "and")
    joined = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} {conj} {names[-1]}"
    return f"{word} {joined}"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _lower_first(text: str) -> str:
    """Lower-case the first letter of a title used mid-sentence ('Lucrări' -> 'lucrări')."""
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        return text[0].lower() + text[1:]
    return text


# --- which rows are suspended ------------------------------------------------------


def is_suspended(row: dict) -> bool:
    """A row counts when a person confirmed it, or it is `affected` and nobody unticked it
    (the same rule as the impact: m1-core's counts_as_lost)."""
    return counts_as_lost(row)


def undecided_rows(analysis: dict) -> list[dict]:
    """`unsure` rows with no human decision: publishing is refused while any exist."""
    return [r for r in analysis.get("stops") or [] if r.get("state") == "unsure" and r.get("confirmed") is None]


def suspended_rows(analysis: dict) -> list[dict]:
    return [r for r in analysis.get("stops") or [] if is_suspended(r)]


# --- cause --------------------------------------------------------------------------

_MAINTENANCE_WORDS = re.compile(r"tramvai|cale de rulare|șin[ăe]|linia de contact|întreținere|mentenanț|"
                                r"revizi|tram track|maintenance", re.I)
_CONSTRUCTION_WORDS = re.compile(r"lucr[ăa]ri|șantier|asfalt|carosabil|canalizare|rețea|construc|"
                                 r"închis|roadworks|works|construction", re.I)


def alert_cause(closure: dict) -> str:
    """CONSTRUCTION for roadworks, MAINTENANCE for track and equipment works, else OTHER_CAUSE.

    A prepared case carries its cause; other closures are classified from their title
    and notice text.
    """
    case = CASES_BY_CLOSURE.get(closure.get("id", ""))
    if case is not None:
        return case.cause
    title = closure.get("title") or {}
    text = " ".join(filter(None, [title.get("ro"), title.get("en"), closure.get("sourceText")]))
    if _MAINTENANCE_WORDS.search(text):
        return "MAINTENANCE"
    if _CONSTRUCTION_WORDS.search(text):
        return "CONSTRUCTION"
    return "OTHER_CAUSE"


def is_open_end(closure: dict) -> bool:
    case = CASES_BY_CLOSURE.get(closure.get("id", ""))
    return bool(case and case.open_end)


# --- building the alerts ------------------------------------------------------------

_MODE_WORDS = {
    "ro": {"bus": "autobuzul", "tram": "tramvaiul", "trolleybus": "troleibuzul"},
    "en": {"bus": "bus", "tram": "tram", "trolleybus": "trolleybus"},
}


def alert_url(closure_id: str, stop_id: str | None = None, base_url: str | None = None) -> str:
    base = (base_url or config.get_settings().public_base_url).rstrip("/")
    return f"{base}/a/{closure_id}" + (f"?stop={stop_id}" if stop_id else "")


def _round10(meters: float) -> int:
    return int(round(float(meters) / 10.0) * 10)


class _Ctx:
    """What every alert of one closure shares: window, reason, temporary lines."""

    def __init__(self, closure: dict):
        self.closure = closure
        self.id = closure["id"]
        self.start = parse_iso(closure["window"]["start"])
        self.end = parse_iso(closure["window"]["end"])
        self.open_end = is_open_end(closure)
        title = closure.get("title") or {}
        self.reason = {"ro": title.get("ro") or "", "en": title.get("en") or title.get("ro") or ""}
        self.temporary = {lang: self._temporary(lang, spoken=False) for lang in ("ro", "en")}
        self.temporary_tts = {lang: self._temporary(lang, spoken=True) for lang in ("ro", "en")}

    def _temporary(self, lang: str, spoken: bool) -> str:
        t = texts()[lang]
        out = []
        for tr in self.closure.get("temporaryRoutes") or []:
            streets = tr.get("streets") or []
            if not streets:
                continue
            mode = _MODE_WORDS[lang].get(tr.get("mode") or "bus", tr.get("mode") or "")
            speak = speak_ro if lang == "ro" else speak_en
            if spoken:
                out.append(t["tts_temporary"].format(mode=mode, line=speak(tr["shortName"]),
                                                     streets=speak(", ".join(streets))))
            else:
                out.append(t["temporary"].format(mode=mode, line=tr["shortName"], streets=" – ".join(streets)))
        return "".join(out)

    def description(self, lang: str, nearest: str) -> str:
        t = texts()[lang]
        return _cap(t["description"].format(
            window=window_text(self.start, self.end, lang, self.open_end),
            reason=self.reason[lang], temporary=self.temporary[lang], nearest=nearest)).strip()

    def tts_description(self, lang: str, nearest: str) -> str:
        t = texts()[lang]
        speak = speak_ro if lang == "ro" else speak_en
        return t["tts_description"].format(
            window=window_tts(self.start, self.end, lang, self.open_end),
            reason=speak(_lower_first(self.reason[lang])),
            temporary=self.temporary_tts[lang], nearest=nearest).strip()


def pick_nearest(rows: list[dict], stop_id: str) -> dict | None:
    """The nearest served stop for a stop's rows: the stop itself when another line still
    serves it (m1-core reports it at 0 m), else the closest one."""
    found = [r["nearestServed"] for r in rows if r.get("nearestServed")]
    own = [n for n in found if str(n.get("stopId")) == str(stop_id)]
    if own:
        return own[0]
    known = [n for n in found if n.get("distanceMeters") is not None]
    if known:
        return min(known, key=lambda n: float(n["distanceMeters"]))
    return found[0] if found else None


def _nearest_texts(nearest: dict | None, short_of: dict[str, str], stop_id: str) -> dict[str, str]:
    out = {}
    for lang in ("ro", "en"):
        t = texts()[lang]
        speak = speak_ro if lang == "ro" else speak_en
        if nearest and str(nearest.get("stopId")) == str(stop_id):
            shorts = [short_of.get(r, r) for r in nearest.get("routeIds") or []]
            out[lang] = t["still_served"].format(lines=lines_phrase(shorts, lang)) if shorts else ""
            out["tts_" + lang] = (t["tts_still_served"].format(lines=lines_phrase(shorts, lang, spoken=True))
                                  if shorts else "")
            continue
        if not nearest or nearest.get("distanceMeters") is None:
            name = nearest.get("name") if nearest else None
            if name:
                out[lang] = t["nearest"].format(name=name, distance="?", lines="").replace(", ? ", " ")
                out[lang] = out[lang].replace(" ()", "")
            else:
                out[lang] = t["nearest_unknown"]
            out["tts_" + lang] = t["tts_nearest_unknown"]
            continue
        meters = _round10(nearest["distanceMeters"])
        shorts = [short_of.get(r, r) for r in nearest.get("routeIds") or []]
        lines = lines_phrase(shorts, lang) if shorts else ""
        text = t["nearest"].format(name=nearest["name"], distance=f"{meters} m", lines=lines)
        out[lang] = text.replace(" ()", "")
        spoken = (ro_count(meters, "metru", "metri") if lang == "ro" else f"{en_words(meters)} metres")
        out["tts_" + lang] = t["tts_nearest"].format(name=speak(nearest["name"]), distance=spoken)
    return out


def _remaining_service(ctx: _Ctx, stop_ids: list[str], suspended: set[tuple[str, str, int]]
                       ) -> dict[str, set[tuple[str, int]]]:
    """(route, direction) pairs that still depart from each stop in the window.

    From the GTFS departure index when the feed covers the window; otherwise from the
    lines the network lists at the stop (no direction).
    """
    out: dict[str, set[tuple[str, int]]] = {s: set() for s in stop_ids}
    if gtfs.is_covered(ctx.start, ctx.end):
        df = gtfs.departures(ctx.start, ctx.end, stop_ids=stop_ids)
        if not df.empty:
            pairs = df[["stop_id", "route_id", "direction_id"]].drop_duplicates()
            for s, r, d in pairs.itertuples(index=False):
                if (str(s), str(r), int(d)) not in suspended:
                    out[str(s)].add((str(r), int(d)))
        return out
    net = load_network()
    suspended_routes = {(s, r) for s, r, _ in suspended}
    for s in stop_ids:
        for r in (net.stop_by_id.get(s) or {}).get("routeIds") or []:
            if (s, r) not in suspended_routes:
                out[s].add((r, -1))
    return out


def _whole_line_actions(closure: dict) -> list[dict]:
    return [a for a in closure.get("routeActions") or []
            if a.get("action") == "suspended" and not a.get("fromStopId") and not a.get("toStopId")]


def build_alerts(closure: dict, analysis: dict, base_url: str | None = None) -> list[Alert]:
    """Alerts of one closure: route-level ones first, then one per affected stop."""
    ctx = _Ctx(closure)
    net = load_network()
    short_of = {r["id"]: r["shortName"] for r in net.routes}
    cause = alert_cause(closure)
    period = [{"start": iso(ctx.start), "end": iso(ctx.end)}]
    suffix = ctx.id.removeprefix("cl_")
    alerts: list[Alert] = []

    for action in _whole_line_actions(closure):
        rid = action["routeId"]
        did = action.get("directionId")
        line = lines_phrase([short_of.get(rid, rid)], "ro")
        line_en = lines_phrase([short_of.get(rid, rid)], "en")
        line_tts = {lang: lines_phrase([short_of.get(rid, rid)], lang, spoken=True) for lang in ("ro", "en")}
        headsign = None
        if did is not None:
            order = gtfs.stop_order(rid, int(did))
            headsign = (net.stop_by_id.get(order[-1]) or {}).get("name") if order else None
        key = "route_header_direction" if headsign else "route_header"
        t_ro, t_en = texts()["ro"], texts()["en"]
        alerts.append(Alert(
            id=f"al_{suffix}_route_{rid}" + (f"_d{did}" if did is not None else ""),
            closureId=ctx.id,
            activePeriod=period,
            cause=cause,
            effect="NO_SERVICE",
            informedEntity=[InformedEntity(routeId=rid, directionId=did)],
            headerText=I18n(ro=_cap(t_ro[key].format(line=line, headsign=headsign)),
                            en=_cap(t_en[key].format(line=line_en, headsign=headsign))),
            descriptionText=I18n(ro=ctx.description("ro", ""), en=ctx.description("en", "")),
            url=alert_url(ctx.id, None, base_url),
            ttsHeaderText=I18n(
                ro=t_ro["tts_" + key].format(line=_cap(line_tts["ro"]), headsign=speak_ro(headsign or "")),
                en=t_en["tts_" + key].format(line=_cap(line_tts["en"]), headsign=speak_en(headsign or ""))),
            ttsDescriptionText=I18n(ro=ctx.tts_description("ro", ""), en=ctx.tts_description("en", "")),
        ))

    rows = suspended_rows(analysis)
    by_stop: dict[str, list[dict]] = {}
    for r in rows:
        by_stop.setdefault(str(r["stopId"]), []).append(r)
    suspended = {(str(r["stopId"]), r["routeId"], int(r["directionId"])) for r in rows}
    remaining = _remaining_service(ctx, list(by_stop), suspended)

    for stop_id, stop_rows in by_stop.items():
        first = stop_rows[0]
        name = first.get("name") or (net.stop_by_id.get(stop_id) or {}).get("name") or stop_id
        shorts = [r.get("routeShortName") or short_of.get(r["routeId"], r["routeId"]) for r in stop_rows]
        near = _nearest_texts(pick_nearest(stop_rows, stop_id), short_of, stop_id)
        entities = sorted({(r["routeId"], int(r["directionId"])) for r in stop_rows})
        t_ro, t_en = texts()["ro"], texts()["en"]
        alerts.append(Alert(
            id=f"al_{suffix}_stop_{stop_id}",
            closureId=ctx.id,
            activePeriod=period,
            cause=cause,
            effect="DETOUR" if remaining.get(stop_id) else "NO_SERVICE",
            informedEntity=[InformedEntity(routeId=r, stopId=stop_id, directionId=d) for r, d in entities],
            headerText=I18n(ro=t_ro["stop_header"].format(stop=name, lines=lines_phrase(shorts, "ro")),
                            en=t_en["stop_header"].format(stop=name, lines=lines_phrase(shorts, "en"))),
            descriptionText=I18n(ro=ctx.description("ro", near["ro"]), en=ctx.description("en", near["en"])),
            url=alert_url(ctx.id, stop_id, base_url),
            ttsHeaderText=I18n(
                ro=t_ro["tts_stop_header"].format(stop=speak_ro(name), lines=lines_phrase(shorts, "ro", True)),
                en=t_en["tts_stop_header"].format(stop=speak_en(name), lines=lines_phrase(shorts, "en", True))),
            ttsDescriptionText=I18n(ro=ctx.tts_description("ro", near["tts_ro"]),
                                    en=ctx.tts_description("en", near["tts_en"])),
        ))
    return alerts


# --- protobuf ------------------------------------------------------------------------


def _translated(target: rt.TranslatedString, text: I18n | dict | None) -> None:
    if text is None:
        return
    data = text.model_dump() if isinstance(text, I18n) else text
    for lang in ("ro", "en"):
        value = data.get(lang)
        if value:
            tr = target.translation.add()
            tr.text = value
            tr.language = lang


def _unix(value: str) -> int:
    return int(parse_iso(value).timestamp())


def feed_message(alerts: list[Alert], timestamp: datetime) -> rt.FeedMessage:
    """FeedMessage, gtfs-realtime 2.0, FULL_DATASET, one entity per alert."""
    msg = rt.FeedMessage()
    msg.header.gtfs_realtime_version = "2.0"
    msg.header.incrementality = rt.FeedHeader.FULL_DATASET
    msg.header.timestamp = int(timestamp.timestamp())
    for a in alerts:
        ent = msg.entity.add()
        ent.id = a.id
        pa = ent.alert
        for p in a.activePeriod:
            tr = pa.active_period.add()
            tr.start = _unix(p.start)
            tr.end = _unix(p.end)
        for ie in a.informedEntity:
            sel = pa.informed_entity.add()
            if ie.routeId:
                sel.route_id = ie.routeId
            if ie.stopId:
                sel.stop_id = ie.stopId
            if ie.directionId is not None:
                sel.direction_id = ie.directionId
        pa.cause = rt.Alert.Cause.Value(a.cause)
        pa.effect = rt.Alert.Effect.Value(a.effect)
        url = pa.url.translation.add()
        url.text = a.url
        _translated(pa.header_text, a.headerText)
        _translated(pa.description_text, a.descriptionText)
        _translated(pa.tts_header_text, a.ttsHeaderText)
        _translated(pa.tts_description_text, a.ttsDescriptionText)
    return msg


def _from_translated(ts: rt.TranslatedString) -> dict | None:
    out = {t.language: t.text for t in ts.translation}
    if not out:
        return None
    return {"ro": out.get("ro") or next(iter(out.values())), "en": out.get("en")}


def alert_dicts_from_feed(data: bytes) -> list[dict]:
    """Decode a feed back to the Alert JSON view (minus closureId, which GTFS-RT has no field for)."""
    msg = rt.FeedMessage()
    msg.ParseFromString(data)
    out = []
    for ent in msg.entity:
        a = ent.alert
        out.append({
            "id": ent.id,
            "activePeriod": [{"start": iso(datetime.fromtimestamp(p.start, TZ)),
                              "end": iso(datetime.fromtimestamp(p.end, TZ))} for p in a.active_period],
            "cause": rt.Alert.Cause.Name(a.cause),
            "effect": rt.Alert.Effect.Name(a.effect),
            "informedEntity": [{"routeId": s.route_id or None, "stopId": s.stop_id or None,
                                "directionId": s.direction_id if s.HasField("direction_id") else None}
                               for s in a.informed_entity],
            "headerText": _from_translated(a.header_text),
            "descriptionText": _from_translated(a.description_text),
            "url": a.url.translation[0].text if a.url.translation else None,
            "ttsHeaderText": _from_translated(a.tts_header_text),
            "ttsDescriptionText": _from_translated(a.tts_description_text),
        })
    return out


# --- validation ----------------------------------------------------------------------

VALIDATOR_MAIN = "edu.usf.cutr.gtfsrtvalidator.lib.Main"
VALIDATOR_REPO = "https://github.com/MobilityData/gtfs-realtime-validator"
VALIDATOR_TIMEOUT_S = 180


class ValidationRule(Model):
    id: str
    severity: Literal["ERROR", "WARNING", "INFO"]
    title: str
    description: str | None
    occurrences: int
    examples: list[str]
    note: I18n | None = None


class ValidatorTool(Model):
    name: str
    version: str | None
    source: str | None


class FeedValidation(Model):
    """What the „validator pe ecran” panel shows (additive type, not in CONTRACT v2.2 yet)."""

    closureId: str | None
    method: Literal["validator", "internal"]
    label: I18n
    tool: ValidatorTool | None
    ranAt: str
    durationSec: float
    passed: bool
    errorCount: int
    warningCount: int
    rules: list[ValidationRule]
    feed: dict
    gtfs: dict
    fallbackReason: str | None
    provenance: list[Provenance]


class ValidatorUnavailable(RuntimeError):
    pass


def validator_jar() -> Path | None:
    tools = config.get_settings().data_dir / "tools"
    jars = sorted(tools.glob("gtfs-realtime-validator*.jar")) if tools.is_dir() else []
    return jars[-1] if jars else None


@lru_cache(maxsize=4)
def _jar_info(path_str: str) -> tuple[str | None, str | None]:
    """(version from the jar's pom.properties, docker image digest written next to it)."""
    version = None
    try:
        with zipfile.ZipFile(path_str) as z:
            for name in z.namelist():
                if name.endswith("gtfs-realtime-validator-lib/pom.properties"):
                    for line in z.read(name).decode("utf-8", "replace").splitlines():
                        if line.startswith("version="):
                            version = line.split("=", 1)[1].strip()
                    break
    except (OSError, zipfile.BadZipFile):
        pass
    image_file = Path(path_str).with_name("gtfs-realtime-validator.image")
    image = image_file.read_text(encoding="utf-8").strip() if image_file.is_file() else None
    return version, image


def _demo_clock_note(rule_id: str) -> I18n | None:
    if rule_id == "W008" and config.get_settings().demo_now is not None:
        return I18n(ro="Așteptat: antetul poartă ora simulată a demo-ului, deci validatorul îl vede vechi.",
                    en="Expected: the header carries the simulated demo time, so the validator sees it as old.")
    return None


def _run_validator(pb: bytes, gtfs_zip: Path) -> tuple[list[ValidationRule], ValidatorTool]:
    jar = validator_jar()
    java = shutil.which("java")
    if jar is None:
        raise ValidatorUnavailable("validator jar missing in $DATA_DIR/tools (run `make data`)")
    if java is None:
        raise ValidatorUnavailable("java not found on PATH")
    work_root = config.get_settings().cache_dir / "gtfsrt-validation"
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work_root) as tmp:
        feed_dir = Path(tmp) / "feed"
        feed_dir.mkdir()
        (feed_dir / "alerts.pb").write_bytes(pb)
        proc = subprocess.run(
            [java, "-cp", str(jar), VALIDATOR_MAIN, "-gtfs", str(gtfs_zip), "-gtfsRealtimePath", str(feed_dir)],
            cwd=tmp, capture_output=True, text=True, timeout=VALIDATOR_TIMEOUT_S,
        )
        out = feed_dir / "alerts.pb.results.json"
        if not out.is_file():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["no output"]
            raise ValidatorUnavailable(f"validator exit {proc.returncode}: {tail[0][:200]}")
        raw = json.loads(out.read_text(encoding="utf-8"))
    rules = []
    for item in raw:
        rule = (item.get("errorMessage") or {}).get("validationRule") or {}
        occ = item.get("occurrenceList") or []
        suffix = rule.get("occurrenceSuffix") or ""
        rid = rule.get("errorId") or "?"
        sev = (rule.get("severity") or "WARNING").upper()
        rules.append(ValidationRule(
            id=rid,
            severity=sev if sev in ("ERROR", "WARNING", "INFO") else "WARNING",
            title=rule.get("title") or rid,
            description=rule.get("errorDescription"),
            occurrences=len(occ),
            examples=[f"{o.get('prefix') or ''} {suffix}".strip() for o in occ[:5]],
            note=_demo_clock_note(rid),
        ))
    version, image = _jar_info(str(jar))
    return rules, ValidatorTool(name="MobilityData gtfs-realtime-validator", version=version,
                                source=image or VALIDATOR_REPO)


def _internal_check(pb: bytes) -> list[ValidationRule]:
    """Protobuf round-trip plus required-field checks, when the validator cannot run."""
    problems: dict[str, list[str]] = {}

    def fail(rule: str, where: str) -> None:
        problems.setdefault(rule, []).append(where)

    msg = rt.FeedMessage()
    try:
        msg.ParseFromString(pb)
    except Exception as exc:  # noqa: BLE001 - any decode error is the finding
        fail("I001", f"decode: {exc}")
        msg = rt.FeedMessage()
    if msg.SerializeToString() != pb:
        fail("I002", "re-encoded bytes differ")
    if msg.header.gtfs_realtime_version != "2.0":
        fail("I003", f"header.gtfs_realtime_version={msg.header.gtfs_realtime_version!r}")
    if not msg.header.timestamp:
        fail("I004", "header.timestamp missing")
    f = gtfs.feed()
    stop_ids = set(f.stops["stop_id"].astype(str))
    route_ids = set(f.routes["route_id"].astype(str))
    seen = set()
    for ent in msg.entity:
        if not ent.id or ent.id in seen:
            fail("I005", f"entity id {ent.id!r} empty or repeated")
        seen.add(ent.id)
        if not ent.HasField("alert"):
            fail("I006", f"entity {ent.id} has no alert")
            continue
        a = ent.alert
        if not a.informed_entity:
            fail("I007", f"entity {ent.id} has no informed_entity")
        for sel in a.informed_entity:
            if not (sel.agency_id or sel.route_id or sel.stop_id or sel.HasField("trip") or sel.HasField("route_type")):
                fail("I008", f"entity {ent.id}: empty informed_entity")
            if sel.stop_id and stop_ids and sel.stop_id not in stop_ids:
                fail("I009", f"entity {ent.id} stop_id {sel.stop_id}")
            if sel.route_id and route_ids and sel.route_id not in route_ids:
                fail("I010", f"entity {ent.id} route_id {sel.route_id}")
        for p in a.active_period:
            if p.start and p.end and p.end <= p.start:
                fail("I011", f"entity {ent.id} active_period end <= start")
        if not a.header_text.translation:
            fail("I012", f"entity {ent.id} has no header_text")
    titles = {
        "I001": "Feed does not decode as a GTFS-RT FeedMessage",
        "I002": "Protobuf round-trip changes the bytes",
        "I003": "Header version is not 2.0",
        "I004": "Header timestamp missing",
        "I005": "Entity id empty or repeated",
        "I006": "Entity without an alert",
        "I007": "Alert without informed_entity",
        "I008": "informed_entity with no selector",
        "I009": "stop_id does not exist in the GTFS stops.txt",
        "I010": "route_id does not exist in the GTFS routes.txt",
        "I011": "active_period ends before it starts",
        "I012": "Alert without header_text",
    }
    return [ValidationRule(id=k, severity="ERROR", title=titles[k], description=None,
                           occurrences=len(v), examples=v[:5]) for k, v in sorted(problems.items())]


def validate_feed(pb: bytes, closure_id: str | None = None) -> FeedValidation:
    """Validate a feed against the GTFS in use. Cached by the feed's sha256."""
    sha = hashlib.sha256(pb).hexdigest()
    cache = config.get_settings().cache_dir / "gtfsrt-validation" / f"{sha}.json"
    if cache.is_file():
        result = FeedValidation.model_validate_json(cache.read_text(encoding="utf-8"))
        return result.model_copy(update={"closureId": closure_id})

    f = gtfs.feed()
    gtfs_zip = gtfs.feed_path()
    t0 = time.monotonic()
    fallback = None
    try:
        if gtfs_zip is None:
            raise ValidatorUnavailable("no GTFS zip")
        rules, tool = _run_validator(pb, gtfs_zip)
        method = "validator"
        label = I18n(ro="Validator oficial MobilityData (gtfs-realtime-validator), rulat pe server",
                     en="Official MobilityData validator (gtfs-realtime-validator), run on our server")
    except (ValidatorUnavailable, subprocess.SubprocessError, OSError, ValueError) as exc:
        fallback = str(exc)
        rules, tool = _internal_check(pb), None
        method = "internal"
        label = I18n(ro="verificare internă (validatorul MobilityData nu a putut rula)",
                     en="internal check (the MobilityData validator could not run)")
    duration = round(time.monotonic() - t0, 2)
    msg = rt.FeedMessage()
    msg.ParseFromString(pb)
    errors = sum(1 for r in rules if r.severity == "ERROR")
    warnings = sum(1 for r in rules if r.severity == "WARNING")
    ran = real_now()
    provenance = [f.provenance]
    if tool is not None:
        provenance.append(prov.provenance(tool.name, ran, url=VALIDATOR_REPO, version=tool.version,
                                          note=f"image {tool.source}" if tool.source else None))
    result = FeedValidation(
        closureId=None,
        method=method,
        label=label,
        tool=tool,
        ranAt=iso(ran),
        durationSec=duration,
        passed=errors == 0,
        errorCount=errors,
        warningCount=warnings,
        rules=rules,
        feed={"entities": len(msg.entity), "bytes": len(pb), "sha256": sha,
              "headerTimestamp": iso(datetime.fromtimestamp(msg.header.timestamp, TZ))},
        gtfs={"file": gtfs_zip.name if gtfs_zip else None, "version": f.version},
        fallbackReason=fallback,
        provenance=provenance,
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(result.model_dump_json(), encoding="utf-8")
    return result.model_copy(update={"closureId": closure_id})
