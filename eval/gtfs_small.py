"""A small, independent GTFS reader for the eval.

It deliberately shares no code with app/ (the backend's GTFS index), so the
numbers it gives are a cross-check of the backend, not a copy of it.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

TZ = ZoneInfo("Europe/Bucharest")


def data_dir() -> Path:
    value = os.environ.get("DATA_DIR")
    if not value:
        raise SystemExit("DATA_DIR is not set: point it at the data cache (see eval/README.md)")
    return Path(value)


def newest_feed_zip(base: Path | None = None) -> Path:
    """The newest GTFS zip in $DATA_DIR/live/gtfs/, else the dated snapshot."""
    base = base or data_dir()
    live = sorted((base / "live" / "gtfs").glob("*.zip"), key=lambda p: p.stat().st_mtime)
    if live:
        return live[-1]
    snaps = sorted(base.glob("smtt-timisoara-ro_*.zip"))
    if not snaps:
        raise FileNotFoundError(f"no GTFS zip under {base}")
    return snaps[-1]


def norm_name(name: str) -> str:
    """Lowercase, no diacritics, no punctuation, single spaces.

    "Canton C.F.R." and "Canton CFR" both become "canton cfr";
    "Dâmbovița (Buclă)" and "Dâmbovița (Bucla)" both become "dambovita (bucla)".
    """
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace(".", "")
    s = re.sub(r"[^a-z0-9() ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace("( ", "(").replace(" )", ")")
    return s


def base_name(name: str) -> str:
    """The stop name without the street in parentheses."""
    return norm_name(re.sub(r"\(.*?\)", "", name))


def gtfs_seconds(hms: str) -> int:
    h, m, s = (int(x) for x in hms.split(":"))
    return h * 3600 + m * 60 + s


@dataclass
class Feed:
    path: Path
    sha256: str
    version: str | None
    start_date: str | None
    end_date: str | None
    routes: pd.DataFrame
    trips: pd.DataFrame
    stops: pd.DataFrame
    stop_times: pd.DataFrame
    calendar: pd.DataFrame
    calendar_dates: pd.DataFrame

    # ---- calendar -------------------------------------------------------
    def services_on(self, day: date) -> set[str]:
        """Service ids active on a service day (calendar + calendar_dates)."""
        ymd = day.strftime("%Y%m%d")
        dow = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][day.weekday()]
        cal = self.calendar
        active = set(
            cal[(cal[dow] == "1") & (cal.start_date <= ymd) & (cal.end_date >= ymd)].service_id
        )
        cd = self.calendar_dates[self.calendar_dates.date == ymd]
        active |= set(cd[cd.exception_type == "1"].service_id)
        active -= set(cd[cd.exception_type == "2"].service_id)
        return active

    # ---- patterns -------------------------------------------------------
    def stop_name(self, stop_id: str) -> str:
        return self.stops.loc[stop_id, "stop_name"]

    def patterns(self, route_id: str, direction_id: int, day: date | None = None) -> list[tuple[tuple[str, ...], int, str]]:
        """Distinct stop sequences of a route+direction, most trips first.

        Returns (stop_ids, trip_count, headsign). With `day`, only trips that
        run on that service day.
        """
        t = self.trips[(self.trips.route_id == route_id) & (self.trips.direction_id == str(direction_id))]
        if day is not None:
            t = t[t.service_id.isin(self.services_on(day))]
        out = []
        for (pat, hs), g in t.groupby(["pattern", "trip_headsign"]):
            out.append((pat, len(g), hs))
        out.sort(key=lambda x: -x[1])
        return out

    def route_stops(self, route_id: str, direction_id: int, day: date | None = None) -> list[str]:
        """Union of the stops of every pattern, in first-seen order (main pattern first)."""
        seen: list[str] = []
        for pat, _, _ in self.patterns(route_id, direction_id, day):
            for s in pat:
                if s not in seen:
                    seen.append(s)
        return seen

    def main_headsign(self, route_id: str, direction_id: int) -> str | None:
        p = self.patterns(route_id, direction_id)
        return p[0][2] if p else None

    # ---- departures -----------------------------------------------------
    def departures(self, day: date, route_ids: set[str] | None = None, direction_id: int | None = None,
                   stop_ids: set[str] | None = None) -> pd.DataFrame:
        """Departure events of one service day (the last stop of a trip is not a departure).

        Adds `when`: the local wall-clock time; GTFS times >= 24:00 roll to the next day.
        """
        t = self.trips[self.trips.service_id.isin(self.services_on(day))]
        if route_ids is not None:
            t = t[t.route_id.isin(route_ids)]
        if direction_id is not None:
            t = t[t.direction_id == str(direction_id)]
        st = self.stop_times[self.stop_times.trip_id.isin(set(t.trip_id))]
        st = st[~st.is_last]
        if stop_ids is not None:
            st = st[st.stop_id.isin(stop_ids)]
        st = st.merge(t[["trip_id", "route_id", "direction_id", "service_id"]], on="trip_id")
        # GTFS times are measured from "noon minus 12h" of the service day
        # (absolute time, so it stays right on DST change days).
        noon_utc = datetime(day.year, day.month, day.day, 12, tzinfo=TZ).astimezone(timezone.utc)
        base = noon_utc - timedelta(hours=12)
        st = st.assign(when=[(base + timedelta(seconds=int(s))).astimezone(TZ) for s in st.dep_s])
        return st


def load_feed(path: Path | None = None) -> Feed:
    path = Path(path) if path else newest_feed_zip()
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    z = zipfile.ZipFile(io.BytesIO(raw))

    def read(name: str) -> pd.DataFrame:
        with z.open(name) as f:
            return pd.read_csv(f, dtype=str, keep_default_na=False)

    info = read("feed_info.txt") if "feed_info.txt" in z.namelist() else pd.DataFrame()
    first = info.iloc[0] if len(info) else {}
    st = read("stop_times.txt")
    st["seq"] = st.stop_sequence.astype(int)
    st = st.sort_values(["trip_id", "seq"]).reset_index(drop=True)
    st["dep_s"] = st.departure_time.where(st.departure_time != "", st.arrival_time).map(gtfs_seconds)
    st["is_last"] = st.trip_id != st.trip_id.shift(-1)
    trips = read("trips.txt")
    pat = st.groupby("trip_id", sort=False).stop_id.apply(tuple).rename("pattern")
    trips = trips.join(pat, on="trip_id")
    cal_dates = read("calendar_dates.txt") if "calendar_dates.txt" in z.namelist() else pd.DataFrame(
        columns=["service_id", "date", "exception_type"])
    return Feed(
        path=path,
        sha256=sha,
        version=first.get("feed_version") if len(info) else None,
        start_date=first.get("feed_start_date") if len(info) else None,
        end_date=first.get("feed_end_date") if len(info) else None,
        routes=read("routes.txt").set_index("route_id", drop=False),
        trips=trips,
        stops=read("stops.txt").set_index("stop_id", drop=False),
        stop_times=st,
        calendar=read("calendar.txt"),
        calendar_dates=cal_dates,
    )
