"""GTFS service calendar and departure index, on the real SMTT feed."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime, timedelta

import pytest

from app.config import TZ
from tests.conftest import needs_data

gtfs = pytest.importorskip("app.common.gtfs")

pytestmark = needs_data


def t(*args) -> datetime:
    return datetime(*args, tzinfo=TZ)


def test_gtfs_ids_equal_city_network_ids():
    from app.common.city import load_network

    f = gtfs.feed()
    net = load_network()
    assert set(f.routes["route_id"]) == set(net.route_by_id)
    assert set(f.stops["stop_id"]) == set(net.stop_by_id)


def test_time_past_midnight_rolls_to_next_day():
    # Trip 5c.1_WDSC_T_01_14 leaves stop 108 at 24:00:00 on its weekday service day.
    f = gtfs.feed()
    st = f.stop_times
    row = st[(st["trip_id"] == "5c.1_WDSC_T_01_14") & (st["stop_id"] == "108")]
    if row.empty:
        pytest.skip("feed changed: trip 5c.1_WDSC_T_01_14 not present")
    assert row["departure_time"].iloc[0] == "24:00:00"
    # Friday 13 Nov 2026 service -> departs Saturday 14 Nov 00:00 Bucharest
    after = gtfs.departures(t(2026, 11, 14, 0, 0), t(2026, 11, 14, 0, 1),
                            stop_ids=["108"], route_ids=["R_AB_5C"])
    hit = after[after["trip_id"] == "5c.1_WDSC_T_01_14"]
    assert len(hit) == 1
    assert int(hit["service_date"].iloc[0]) == 20261113
    # at 13 Nov 00:00 the same trip belongs to Thursday 12 Nov's service, never to 13 Nov
    before = gtfs.departures(t(2026, 11, 13, 0, 0), t(2026, 11, 13, 0, 1),
                             stop_ids=["108"], route_ids=["R_AB_5C"])
    same_trip = before[before["trip_id"] == "5c.1_WDSC_T_01_14"]
    assert set(same_trip["service_date"].astype(int)) <= {20261112}


def test_calendar_dates_exception_replaces_weekday_service():
    # Monday 30 Nov 2026: calendar_dates removes S_TV_4_WDSC and adds S_TV_4_WEDU.
    mon_30 = gtfs.service_ids_on(date(2026, 11, 30))
    mon_23 = gtfs.service_ids_on(date(2026, 11, 23))
    assert "S_TV_4_WDSC" in mon_23 and "S_TV_4_WEDU" not in mon_23
    assert "S_TV_4_WDSC" not in mon_30 and "S_TV_4_WEDU" in mon_30

    f = gtfs.feed()
    service_of = dict(zip(f.trips["trip_id"], f.trips["service_id"]))
    deps = gtfs.departures(t(2026, 11, 30, 4), t(2026, 12, 1, 0), route_ids=["R_TV_4"])
    services = {service_of[str(tr)] for tr in deps["trip_id"].unique()}
    assert services == {"S_TV_4_WEDU"}


def test_last_stop_is_not_a_departure():
    order = gtfs.stop_order("R_TV_4", 0)
    assert len(order) > 2
    deps = gtfs.departures(t(2026, 11, 9, 0), t(2026, 11, 10, 0),
                           stop_ids=[order[-1]], route_ids=["R_TV_4"], direction_id=0)
    assert len(deps) == 0


def _independent_count(zip_path, stop_id, route_id, direction_id, day, start_hms, end_hms) -> int:
    """Count straight from the zip with the csv module: calendar, exceptions, times."""
    with zipfile.ZipFile(zip_path) as z:
        def rows(name):
            return list(csv.DictReader(io.StringIO(z.read(name).decode("utf-8-sig"))))

        ymd = day.strftime("%Y%m%d")
        wd = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")[day.weekday()]
        active = {c["service_id"] for c in rows("calendar.txt")
                  if c[wd] == "1" and c["start_date"] <= ymd <= c["end_date"]}
        for c in rows("calendar_dates.txt"):
            if c["date"] == ymd:
                (active.add if c["exception_type"] == "1" else active.discard)(c["service_id"])
        trips = {r["trip_id"] for r in rows("trips.txt")
                 if r["route_id"] == route_id and r["direction_id"] == str(direction_id)
                 and r["service_id"] in active}
        st = [r for r in rows("stop_times.txt") if r["trip_id"] in trips]
    last_seq = {}
    for r in st:
        last_seq[r["trip_id"]] = max(last_seq.get(r["trip_id"], 0), int(r["stop_sequence"]))

    def sec(hms):
        h, m, s = hms.split(":")
        return int(h) * 3600 + int(m) * 60 + int(s)

    lo, hi = sec(start_hms), sec(end_hms)
    return sum(1 for r in st if r["stop_id"] == stop_id and int(r["stop_sequence"]) < last_seq[r["trip_id"]]
               and lo <= sec(r["departure_time"]) < hi)


def test_real_count_matches_independent_query():
    # Hero case: stop 61 (Piața Sfânta Maria), line 4 towards AEM, Sunday 8 Nov 2026 10:00-18:00.
    got = gtfs.count_departures(t(2026, 11, 8, 10), t(2026, 11, 8, 18),
                                stop_ids=["61"], route_ids=["R_TV_4"], direction_id=0)
    want = _independent_count(gtfs.feed().path, "61", "R_TV_4", 0, date(2026, 11, 8), "10:00:00", "18:00:00")
    assert got == want and got > 0
    by_key = gtfs.count_by_key(t(2026, 11, 8, 10), t(2026, 11, 8, 18), keys=[("61", "R_TV_4", 0)])
    assert by_key == {("61", "R_TV_4", 0): got}


def test_minute_counts_sum_to_count():
    s, e = t(2026, 11, 9, 6), t(2026, 11, 9, 9)
    m = gtfs.minute_counts(s, e, route_ids=["R_AB_E3"])
    assert len(m) == 180
    assert int(m.sum()) == gtfs.count_departures(s, e, route_ids=["R_AB_E3"])


def test_outside_feed_is_not_covered():
    first, last = gtfs.coverage()
    assert gtfs.is_covered(t(2026, 11, 8, 10), t(2026, 11, 8, 18))
    before = datetime.combine(first - timedelta(days=1), datetime.min.time(), TZ)
    assert not gtfs.is_covered(before, before + timedelta(hours=2))
