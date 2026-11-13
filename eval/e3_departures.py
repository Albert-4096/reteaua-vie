"""SPEC 5.2: scheduled E3 departures per weekday at the stops notice 11065 suspends.

Stops: the names in the notice, per direction, resolved to GTFS stop ids on
E3's own pattern (eval/labels/11065.json, made by make_labels.py).
Count: departures only (the last stop of a trip is an arrival), straight from
the GTFS (calendar + calendar_dates), for each weekday inside the closure
window. A calendar day counts the departures whose local clock time falls on
that day, so trips past 24:00 of the previous service day count on the next
day.

Run (from repo/):  uv run --no-project --with pandas python eval/e3_departures.py [--write]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gtfs_small import TZ, Feed, load_feed  # noqa: E402

HERE = Path(__file__).resolve().parent
ROUTE = "R_AB_E3"


def suspended_stops() -> dict[int, list[str]]:
    lab = json.loads((HERE / "labels" / "11065.json").read_text(encoding="utf-8"))
    return {a["directionId"]: a["suspendedStopIds"] for a in lab["gold"]["routeActions"] if a["routeId"] == ROUTE}


def calendar_day_count(feed: Feed, day: date, stops: set[str], direction: int | None, routes: set[str] | None) -> int:
    n = 0
    for service_day in (day - timedelta(days=1), day):
        dep = feed.departures(service_day, routes, direction, stops)
        n += int(sum(1 for w in dep["when"] if w.date() == day))
    return n


def compute(feed: Feed | None = None) -> dict:
    feed = feed or load_feed()
    stops = suspended_stops()
    lab = json.loads((HERE / "labels" / "11065.json").read_text(encoding="utf-8"))
    start = datetime.fromisoformat(lab["window"]["start"]).astimezone(TZ)
    end = datetime.fromisoformat(lab["window"]["end"]).astimezone(TZ)
    days = []
    d = start.date()
    while datetime(d.year, d.month, d.day, tzinfo=TZ) < end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)

    per_day = []
    for day in days:
        row = {"date": day.isoformat(), "weekday": day.strftime("%A"),
               "services": sorted(s for s in feed.services_on(day) if s.startswith("S_AB_E3_")),
               "byDirection": {}, "serviceDayTotal": 0}
        total = 0
        for direction, ids in stops.items():
            sd = len(feed.departures(day, {ROUTE}, direction, set(ids)))
            cd = calendar_day_count(feed, day, set(ids), direction, {ROUTE})
            row["byDirection"][str(direction)] = {"stops": len(ids), "calendarDay": cd, "serviceDay": sd}
            total += cd
            row["serviceDayTotal"] += sd
        all_ids = set().union(*map(set, stops.values()))
        row["calendarDayTotal"] = total
        row["allRoutesAtTheseStops"] = calendar_day_count(feed, day, all_ids, None, None)
        per_day.append(row)

    headline = per_day[0]
    same = len({r["calendarDayTotal"] for r in per_day}) == 1
    headsigns = {str(d): feed.main_headsign(ROUTE, d) for d in stops}
    return {
        "figure": headline["calendarDayTotal"],
        "date": headline["date"],
        "sameOnEveryWeekdayOfTheWindow": same,
        "label": {"ro": "plecări programate E3 pe zi lucrătoare în stațiile suspendate (anunț STPT 11065)",
                  "en": "scheduled E3 departures per weekday at the stops suspended by STPT notice 11065"},
        "stops": {str(d): [{"stopId": s, "name": feed.stop_name(s)} for s in ids] for d, ids in stops.items()},
        "headsigns": headsigns,
        "stopIdsTotal": sum(len(v) for v in stops.values()),
        "weekdays": per_day,
        "method": ("GTFS stop_times of trips of route R_AB_E3 whose service runs that day (calendar.txt weekday flags "
                   "and date range, then calendar_dates.txt add/remove). Departures only: the last stop of a trip is "
                   "not counted. Stops: the names the notice suspends, per direction, matched to E3's own pattern. "
                   "Calendar day = local clock (Europe/Bucharest); times >= 24:00 roll to the next day."),
        "feed": {"version": feed.version, "file": feed.path.name, "sha256": feed.sha256,
                 "validFrom": feed.start_date, "validTo": feed.end_date},
        "provenance": [{
            "source": "SMTT GTFS", "url": "https://smtt.ro", "version": feed.version,
            "fetchedAt": datetime.fromtimestamp(feed.path.stat().st_mtime, TZ).isoformat(timespec="seconds"),
            "note": "computed by eval/e3_departures.py",
        }],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="also write eval/results/e3_departures.json")
    args = ap.parse_args()
    res = compute()
    text = json.dumps(res, ensure_ascii=False, indent=2)
    print(text)
    if args.write:
        (HERE / "results").mkdir(exist_ok=True)
        (HERE / "results" / "e3_departures.json").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
