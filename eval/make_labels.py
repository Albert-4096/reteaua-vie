"""Write the gold labels in eval/labels/<postId>.json.

The labels were read by hand from the five STPT notices. This script holds
those readings (stop names per line and direction, the action, the notes) and
resolves every stop name to a GTFS stop id on the line's own stop pattern, so
the ids are reproducible and a reviewer can check each match.

A stop of a line+direction is in exactly one of three lists:
  suspendedStopIds  the notice takes it away (gold positive)
  keptStopIds       the notice keeps it (gold negative)
  uncertainStopIds  the notice does not say clearly; not scored, see `notes`

Run (from repo/):  uv run --with pandas python eval/make_labels.py
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gtfs_small import Feed, base_name, data_dir, feed_zip, load_feed, norm_name  # noqa: E402

HERE = Path(__file__).resolve().parent
LABELLED_BY = "AI-assisted from the notice text; human review pending"


# ---------------------------------------------------------------------------
# notice text
# ---------------------------------------------------------------------------

def post_file(post_id: int) -> Path:
    files = sorted((data_dir() / "live" / "stpt-posts").glob(f"{post_id}_*.json"))
    if not files:
        raise FileNotFoundError(f"notice {post_id} not found in $DATA_DIR/live/stpt-posts/")
    return files[-1]


def html_to_text(raw: str) -> str:
    t = re.sub(r"<br\s*/?>", "\n", raw)
    t = re.sub(r"</(p|li|h\d|div)>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in t.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def read_post(post_id: int) -> dict:
    p = post_file(post_id)
    d = json.loads(p.read_text(encoding="utf-8"))
    title = d["title"]["rendered"] if isinstance(d["title"], dict) else d["title"]
    content = d["content"]["rendered"] if isinstance(d["content"], dict) else d["content"]
    return {
        "postId": d["id"],
        "title": html.unescape(title),
        "postDate": d["date"] + "+02:00",
        "sourceUrl": d["link"],
        "sourceFile": str(p.relative_to(data_dir())),
        "noticeText": html_to_text(content),
    }


# ---------------------------------------------------------------------------
# name resolution
# ---------------------------------------------------------------------------

def resolve(feed: Feed, name: str, candidates: list[str], manual: dict[str, str] | None = None) -> dict:
    """Match one notice stop name to a stop id among `candidates` (the line's pattern)."""
    manual = manual or {}
    if name in manual:
        sid = manual[name]
        return {"name": name, "stopId": sid or None, "gtfsName": feed.stop_name(sid) if sid else None,
                "match": "manual" if sid else "none"}
    for how, key in (("exact", lambda s: s), ("normalized", norm_name), ("base-name", base_name)):
        want = key(name)
        hits = [s for s in candidates if key(feed.stop_name(s)) == want]
        if len(hits) == 1:
            return {"name": name, "stopId": hits[0], "gtfsName": feed.stop_name(hits[0]), "match": how}
        if len(hits) > 1:
            return {"name": name, "stopId": None, "gtfsName": None, "match": "ambiguous",
                    "candidates": hits}
    return {"name": name, "stopId": None, "gtfsName": None, "match": "none"}


def route_meta(feed: Feed, route_id: str, direction_id: int, day: date) -> dict:
    pats = feed.patterns(route_id, direction_id, day)
    return {
        "routeId": route_id,
        "shortName": feed.routes.loc[route_id, "route_short_name"],
        "directionId": direction_id,
        "headsign": pats[0][2] if pats else feed.main_headsign(route_id, direction_id),
        "patternStopIds": feed.route_stops(route_id, direction_id, day),
    }


def entry(feed: Feed, route_id: str, d: int, day: date, action: str, *, suspended=(), kept=None,
          uncertain=(), stop_names=None, resolved=None, notes=()) -> dict:
    meta = route_meta(feed, route_id, d, day)
    pat = meta["patternStopIds"]
    suspended = [s for s in pat if s in set(suspended)]
    uncertain = [s for s in pat if s in set(uncertain) and s not in suspended]
    if kept is None:
        kept = [s for s in pat if s not in suspended and s not in uncertain]
    else:
        kept = [s for s in pat if s in set(kept)]
    missing = set(pat) - set(suspended) - set(kept) - set(uncertain)
    assert not missing, f"{route_id}/{d}: unlabelled stops {missing}"
    meta.update({
        "action": action,
        "stopNames": stop_names,
        "resolved": resolved,
        "suspendedStopIds": suspended,
        "keptStopIds": kept,
        "uncertainStopIds": uncertain,
        "suspendedStopNames": [feed.stop_name(s) for s in suspended],
        "notes": list(notes),
    })
    return meta


def between(pat: list[str], first: str, last: str) -> list[str]:
    i, j = pat.index(first), pat.index(last)
    return pat[i:j + 1]


# ---------------------------------------------------------------------------
# the five notices
# ---------------------------------------------------------------------------

def label_11067(feed: Feed) -> dict:
    """Hero: tram works on Bd. 16 Decembrie 1989, Sun 8 Nov 10:00-18:00."""
    day = date(2026, 11, 8)
    out = []
    # Line 4: suspended for the whole works, both directions.
    for d in (0, 1):
        pat = feed.route_stops("R_TV_4", d, day)
        out.append(entry(feed, "R_TV_4", d, day, "suspended", suspended=pat, kept=[],
                         notes=["„linia 4 va fi suspendată pe întreaga durată a lucrărilor”: every stop, both directions."]))

    # Lines 2 and 7 lose the section north of Piața Maria (Catedrala ... Calea Torontalului).
    keep2 = ["Shopping City", "Piața Maria", "Gheorghe Doja", "Piața Bălcescu", "AEM"]
    p20 = feed.route_stops("R_TV_2", 0, day)
    p21 = feed.route_stops("R_TV_2", 1, day)
    north0 = between(p20, "85", "907")      # Catedrala Mitropolitană -> Calea Torontalului
    north1 = between(p21, "896", "86")      # Calea Torontalului -> Catedrala Mitropolitană
    res20 = [resolve(feed, n, p20, {"Piața Maria": "59"}) for n in keep2]
    res21 = [resolve(feed, n, p21, {"Piața Maria": "60"}) for n in keep2]
    common2 = [
        "„linia 2 va circula, tur – retur, pe traseul Shopping City – Piața Maria – Gheorghe Doja – Piața Bălcescu – AEM”: "
        "kept = line 2 stops from Shopping City to Piața Maria; the rest of line 2 (Catedrala Mitropolitană to Calea Torontalului) is suspended.",
        "Gheorghe Doja, Piața Bălcescu and AEM are not on line 2's GTFS pattern (they are on line 4's): line 2 takes line 4's south "
        "branch to AEM. Those stops are served by line 2 during the works but they are not line 2 stops in the GTFS, so they are not labelled here.",
        "The notice calls this a new route, not just a shortening; SPEC 5.1 models it as `shortened` with keepStopIds.",
    ]
    out.append(entry(feed, "R_TV_2", 0, day, "shortened", suspended=north0, stop_names=keep2, resolved=res20,
                     notes=common2))
    out.append(entry(feed, "R_TV_2", 1, day, "shortened", suspended=north1 + ["61"], stop_names=keep2, resolved=res21,
                     notes=common2 + [
                         "Stop 61 „Piața Sfânta Maria (16 Decembrie 1989)” is labelled suspended: in this GTFS it is used only by trams "
                         "arriving from Catedrala Mitropolitană (2 dir 1, 4 dir 0, 7 dir 1). A line 2 tram coming from Gheorghe Doja "
                         "reaches Piața Maria at stop 60 (as line 1 does). Reviewer: confirm."]))

    keep7 = ["Depou Dâmbovița", "Gara de Nord"]
    p70 = feed.route_stops("R_TV_7", 0, day)
    p71 = feed.route_stops("R_TV_7", 1, day)
    n70 = between(p70, "85", "907")
    n71 = between(p71, "896", "86") + ["61"]
    res7 = [resolve(feed, n, p70 + p71, {"Depou Dâmbovița": "890", "Gara de Nord": ""}) for n in keep7]
    note7 = [
        "„linia 7 va circula, tur – retur, pe traseul: Depou Dâmbovița – Gara de Nord”: the notice names only the two ends. "
        "Gara de Nord is not on line 7's GTFS pattern.",
        "Certain: the section Catedrala Mitropolitană – Calea Torontalului is lost (as for lines 2 and 4).",
        "Not certain (labelled uncertain, not scored): the path from Dâmbovița to Gara de Nord. Either (a) the usual line 7 ring "
        "(Banatul – Piața Veteranilor – Victor Hugo – Drubeta – Memorandumului – Piața Bălcescu – Parcul C. Sylva – Piața Maria) "
        "and then Piața Mocioni – Bd. Regele Carol I – Gara de Nord, or (b) Banatul – Dâmbovița (Ion Barac) – Crizantemelor – "
        "Bd. Iuliu Maniu – Bd. Regele Carol I – Gara de Nord (line 2's track). Under (b) the ring stops are lost too.",
        "Kept for sure: stop 890 Dâmbovița (the depot end).",
    ]
    for d, pat, north in ((0, p70, n70), (1, p71, n71)):
        unc = [s for s in pat if s not in north and s != "890"]
        out.append(entry(feed, "R_TV_7", d, day, "shortened", suspended=north, kept=["890"], uncertain=unc,
                         stop_names=keep7, resolved=res7,
                         notes=note7 + (["Stop 61: see the line 2 note (only trams from Catedrala use it)."] if d == 1 else [])))
    return {
        "window": {"start": "2026-11-08T10:00:00+02:00", "end": "2026-11-08T18:00:00+02:00"},
        "cause": "MAINTENANCE",
        "routeActions": out,
        "temporaryRoutes": [{
            "shortName": "4b", "mode": "bus",
            "streets": ["Piața Iuliu Maniu", "Bulevardul 16 Decembrie 1989", "Bulevardul Regele Ferdinand I",
                        "Strada Doctor Iosif Nemoianu", "Strada Coriolan Brediceanu", "Calea Bogdăneștilor",
                        "Bulevardul Cetății", "Calea Torontalului"],
            "stopIds": None,
            "notes": ["The notice gives streets, no stops: stopIds is null. „cu retur pe același traseu”."],
        }],
        "notes": [
            "The works are on Bd. 16 Decembrie 1989, „pe sensul de circulație către Podul Maria”, on 10–15 m; the exact point is not given.",
            "Tram line 8 also stops at Piața Maria (stops 59, 60) and is not named in the notice: not labelled (not affected by the notice).",
            "Pattern day: Sunday 8 Nov 2026 (service WEDU).",
        ],
    }


def label_11065(feed: Feed) -> dict:
    """E3, Str. Ardealului closed 7 Nov 04:00 - 12 Nov 24:00."""
    day = date(2026, 11, 9)
    names = {
        0: ["Dâmbovița (Buclă)", "Baba Novac", "Opre Gogu (Ardealului)", "Păcii (Ardealului)", "Canton CFR",
            "Liceul Auto (Ardealului)"],
        1: ["Liceul Auto (Ardealului)", "Canton CFR", "Păcii (Ardealului)", "Opre Gogu (Ardealului)",
            "Dâmbovița (Buclă)"],
    }
    towards = {0: "către Elba (Parcul Industrial Freidorf)", 1: "către Apicultorilor"}
    out = []
    for d in (0, 1):
        pat = feed.route_stops("R_AB_E3", d, day)
        res = [resolve(feed, n, pat) for n in names[d]]
        assert all(r["stopId"] for r in res), res
        out.append(entry(feed, "R_AB_E3", d, day, "rerouted", suspended=[r["stopId"] for r in res],
                         stop_names=names[d], resolved=res,
                         notes=[f"Direction from the notice: „Sensul de deplasare {towards[d]}” matched to the GTFS headsign.",
                                "Spelling differs from the GTFS: „Buclă” vs „Bucla”, „Canton CFR” vs „Canton C.F.R.” (normalized match).",
                                "Every other E3 stop keeps its service: the detour (Budai Deleanu – Nicolae Andreescu – Ion Slavici, "
                                "back via Banatul) has no new stops named in the notice."]))
    return {
        "window": {"start": "2026-11-07T04:00:00+02:00", "end": "2026-11-13T00:00:00+02:00"},
        "cause": "CONSTRUCTION",
        "routeActions": out,
        "temporaryRoutes": [],
        "notes": [
            "„12 noiembrie 2026, ora 24 00” is written as 2026-11-13T00:00+02:00.",
            "Closure: Str. Ardealului between Str. Rahovei and Str. Martir Gogu Opre, both directions.",
            "Pattern day: Monday 9 Nov 2026 (service WDSC). GTFS 4.31 still has the normal E3 pattern on Str. Ardealului.",
        ],
    }


def label_11060(feed: Feed) -> dict:
    """Mocioni diversion of metropolitan lines, from 2 Nov until the works end."""
    day = date(2026, 11, 13)
    served = {
        ("R_AB_M32", 0): ["C. Brâncoveanu (pe b-dul Constantin Brâncoveanu)", "Ciprian Porumbescu (Constantin Brâncoveanu)",
                          "Calea Șagului (Bd. Dâmbovița)", "Biserica Catolică Fratelia (Biserică)"],
        ("R_AB_M32", 1): ["Piața Veteranilor (Calea Șagului)", "Calea Șagului (b-dul Liviu Rebreanu)",
                          "Piața Iuliu Maniu (16 Decembrie 1989)", "C. Brâncoveanu (pe b-dul Constantin Brâncoveanu)"],
        ("R_AB_M36", 0): ["Iuliu Maniu (Budai Deleanu)", "Crizantemelor (Budai Deleanu)", "Dâmbovița (Banatul)",
                          "Opre Gogu (Nicolae Andreescu)", "Păcii", "V. Simionescu", "Liceul Auto", "Podgoriei",
                          "Constantin Nottara", "Răscoala din 1907", "Polonă", "Fabrica de Zahăr", "Comtim (Smithfield)"],
        ("R_AB_M36", 1): ["Comtim (Smithfield)", "Fabrica de Zahăr", "Polonă", "Răscoala din 1907", "Constantin Nottara",
                          "Podgoriei", "Liceul Auto (Nicolae Andreescu)", "V. Simionescu", "Păcii",
                          "Opre Gogu (Nicolae Andreescu)", "Dâmbovița (Banatul)", "Transilvania (Budai Deleanu)",
                          "Piața Iuliu Maniu"],
    }
    m37_out = ["Piața Iuliu Maniu (Calea Șagului)", "Calea Șagului", "Piața Veteranilor", "B.A.T.M.", "Ovidiu Cotruș",
               "Leroy Merlin", "Incontro (DN 59)"]
    m37_in = ["Incontro (DN 59)", "Auchan", "Ovidiu Cotruș", "B.A.T.M.", "Piața Veteranilor", "Calea Șagului",
              "Piața Iuliu Maniu"]
    for r in ("R_AB_M37", "R_AB_M38", "R_AB_M51"):
        served[(r, 0)] = m37_out
        served[(r, 1)] = m37_in
    served[("R_AB_M46", 0)] = ["Piața Iuliu Maniu (Calea Șagului)", "Calea Șagului", "Piața Veteranilor", "Ovidiu Cotruș",
                               "Leroy Merlin", "Incontro (DN 59)"]
    served[("R_AB_M46", 1)] = ["Incontro (DN 59)", "Leroy Merlin", "Auchan", "Ovidiu Cotruș", "Piața Veteranilor",
                               "Calea Șagului", "Piața Iuliu Maniu"]
    manual = {
        "Ciprian Porumbescu (Constantin Brâncoveanu)": "479",
        "Iuliu Maniu (Budai Deleanu)": "332",
        "Biserica Catolică Fratelia (Biserică)": "",
    }
    # M32 outbound: the notice's list ends with „Biserica Catolică Fratelia (Biserică) – limită UAT”; the GTFS
    # pattern stops at Piața Veteranilor (Calea Șagului) before leaving the city. Not named, but on the way.
    extra_uncertain = {("R_AB_M32", 0): ["293"]}
    out = []
    for (rid, d), names in served.items():
        pat = feed.route_stops(rid, d, day)
        res = [resolve(feed, n, pat, manual) for n in names]
        hit: set[str] = set()
        unc: list[str] = []
        # Per trip pattern: the modified part is the city part, from the city end of the
        # pattern to the last (outbound) or from the first (inbound) stop on the served list.
        for p, _, _ in feed.patterns(rid, d, day):
            p = list(p)
            ph = [r["stopId"] for r in (resolve(feed, n, p, manual) for n in names) if r["stopId"] in p]
            hit |= set(ph)
            if not ph:
                continue
            idx = sorted(p.index(s) for s in ph)
            city = p[: idx[-1] + 1] if d == 0 else p[idx[0]:]
            unc += [s for s in city if s not in ph and s not in unc]
        unc = [s for s in unc if s not in hit] + extra_uncertain.get((rid, d), [])
        notes = [
            "GTFS 4.31 (valid from 5 Nov) already runs this line on the diverted route: every served stop of the notice "
            "is on the GTFS pattern. Against this feed the notice suspends no stop of the pattern, so suspendedStopIds is empty. "
            "The pre-diversion stops (the headsign still says „Mocioni”) are not in our feed, so they cannot be labelled.",
        ]
        if unc:
            notes.append("On the city part of the GTFS pattern but not on the notice's served list: "
                         + ", ".join(f"{s} {feed.stop_name(s)}" for s in unc)
                         + ". Probably an omission in the notice (the bus passes there), so uncertain, not suspended.")
        miss = [r["name"] for r in res if r["match"] == "none"]
        if miss:
            notes.append("Served names with no stop on the GTFS pattern: " + ", ".join(miss) + ".")
        for r in res:
            if r["match"] == "ambiguous":
                notes.append(f"„{r['name']}” matches stops {', '.join(r['candidates'])}: different trip variants of "
                             "this line end at different platforms; each variant uses one of them.")
        out.append(entry(feed, rid, d, day, "rerouted", suspended=[], uncertain=unc, stop_names=names, resolved=res,
                         notes=notes))
    return {
        "window": {"start": "2026-11-02T00:00:00+02:00", "end": None},
        "cause": "CONSTRUCTION",
        "routeActions": out,
        "temporaryRoutes": [],
        "notes": [
            "Open end: „până la finalizarea lucrărilor”. SPEC 5.3 uses 2026-12-31T23:59:59+02:00 for the demo; the label keeps null.",
            "S8 (school line) is named in the notice but is not in the GTFS: not labelled.",
            "The notice lists the stops that ARE served (per direction), not the suspended ones.",
            "Pattern day: Friday 13 Nov 2026.",
        ],
    }


def label_11062(feed: Feed) -> dict:
    """E3 resumes towards Elba via Ioan Slavici – Răscoala; the Polonă bridge is closed."""
    day = date(2026, 11, 9)
    out = []
    for d in (0, 1):
        out.append(entry(feed, "R_AB_E3", d, day, "rerouted", suspended=[], stop_names=None, resolved=[],
                         notes=["„stațiile amplasate pe strada Polonă, în zona podului, nu vor mai fi utilizate”: no stop is named.",
                                "GTFS 4.31 (valid from 5 Nov) already routes E3 via Răscoala din 1907 and has no Polonă stop on E3 "
                                "(E7 and M36 still stop at Polonă (Pasaj Freidorf), ids 344/314). So no stop of the current E3 "
                                "pattern is suspended. The pre-detour Polonă stops of E3 cannot be named from this feed."]))
    return {
        "window": {"start": "2026-11-04T00:00:00+02:00", "end": None},
        "cause": "CONSTRUCTION",
        "routeActions": out,
        "temporaryRoutes": [],
        "notes": [
            "„Începând de mâine” in a post of 3 Nov 19:00: start 4 Nov; no end date.",
            "Expected parser behaviour: route E3 found, the stop list sent to review („neclar”), since no stop name is given.",
        ],
    }


def label_11058(feed: Feed) -> dict:
    """Timetable and route extensions for M30, M29, M35, M44, S7: no stop is suspended."""
    return {
        "window": {"start": "2026-11-02T00:00:00+02:00", "end": None},
        "cause": None,
        "routeActions": [],
        "temporaryRoutes": [],
        "notes": [
            "Not a closure: M30 and S7 are extended, M29/M35/M44 change timetables. Gold: no suspended stop.",
            "Any stop the pipeline marks as suspended for this notice is a false positive.",
            "S7 is not in the GTFS.",
        ],
    }


LABELLERS = {11067: label_11067, 11065: label_11065, 11060: label_11060, 11062: label_11062, 11058: label_11058}


def main() -> None:
    feeds: dict = {}
    for pid, fn in LABELLERS.items():
        lab = read_post(pid)
        # the feed in force when the notice was posted (loaded once per zip)
        path = feed_zip(at=lab["postDate"])
        if path not in feeds:
            feeds[path] = load_feed(path)
        feed = feeds[path]
        gold = fn(feed)
        lab.update({
            "labelledBy": LABELLED_BY,
            "feed": {"version": feed.version, "file": feed.path.name, "sha256": feed.sha256,
                     "validFrom": feed.start_date, "validTo": feed.end_date},
            "window": gold.pop("window"),
            "cause": gold.pop("cause"),
            "gold": gold,
        })
        out = HERE / "labels" / f"{pid}.json"
        out.write_text(json.dumps(lab, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        n_s = sum(len(a["suspendedStopIds"]) for a in gold["routeActions"])
        n_u = sum(len(a["uncertainStopIds"]) for a in gold["routeActions"])
        print(f"{pid}: {len(gold['routeActions'])} route-directions, {n_s} suspended, {n_u} uncertain -> {out.name}")


if __name__ == "__main__":
    main()
