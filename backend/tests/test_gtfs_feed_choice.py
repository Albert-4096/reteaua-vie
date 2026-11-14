"""gtfs.feed_path(): the feed in force at a date, not the newest file.

SMTT published 4.32 on 14 Nov, valid from 16 Nov; on 8 Nov (the demo clock)
the feed in force is still 4.31. Two tiny hand-made zips, no real data.
"""

from __future__ import annotations

import os
import zipfile
from datetime import date, datetime

import pytest

from app import config
from app.common import gtfs
from app.config import TZ


def tiny_zip(path, version: str, start: str | None, cal_start: str = "20261101") -> None:
    info = ("feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date,feed_version\n"
            f"Test,https://example.invalid,ro,{start or ''},20261231,{version}\n")
    files = {
        "routes.txt": "route_id,route_short_name,route_type\nR_TV_1,1,0\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\n1,A,45.75,21.22\n2,B,45.755,21.225\n",
        "trips.txt": "route_id,service_id,trip_id,direction_id,trip_headsign\nR_TV_1,LV,t-1,0,B\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                          "t-1,08:00:00,08:00:00,1,1\nt-1,08:05:00,08:05:00,2,2\n",
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                        f"LV,1,1,1,1,1,1,1,{cal_start},20261231\n",
        "feed_info.txt": info,
    }
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)


@pytest.fixture
def feeds(tmp_path, monkeypatch):
    """$LIVE_DIR/gtfs with 4.31 (from 5 Nov) and a newer file 4.32 (from 16 Nov); demo clock 8 Nov."""
    live = tmp_path / "live"
    (live / "gtfs").mkdir(parents=True)
    old, new = live / "gtfs" / "smtt_a.zip", live / "gtfs" / "smtt_b.zip"
    tiny_zip(old, "4.31", "20261105", "20261105")
    tiny_zip(new, "4.32", "20261116", "20261116")
    os.utime(old, (1_000_000_000, 1_000_000_000))        # 4.32 is the newest file
    fake = config.Settings(env_file=None, data_dir=tmp_path, live_dir=live,
                           demo_now=datetime(2026, 11, 8, 12, tzinfo=TZ), data_freeze=False,
                           public_base_url="http://test")
    monkeypatch.setattr(config, "get_settings", lambda: fake)
    monkeypatch.setattr(gtfs, "get_settings", lambda: fake)
    return old, new


def test_feed_in_force_at_a_date(feeds):
    old, new = feeds
    assert gtfs.feed_path(date(2026, 11, 8)) == old
    assert gtfs.feed_path(datetime(2026, 11, 20, 9, tzinfo=TZ)) == new
    assert gtfs.feed_path(date(2026, 11, 16)) == new          # the start day itself
    assert gtfs.feed(date(2026, 11, 8)).version == "4.31"
    assert gtfs.feed(date(2026, 11, 20)).version == "4.32"


def test_default_is_the_app_clock_not_the_newest_file(feeds, monkeypatch):
    old, new = feeds
    assert gtfs.feed_path() == old                              # DEMO_NOW 8 Nov
    assert gtfs.feed().version == "4.31"
    assert gtfs.feed().provenance.version == "4.31"
    assert gtfs.feed_file_time() == gtfs.file_mtime(old)
    assert gtfs.service_ids_on(date(2026, 11, 8)) == {"LV"}
    real = config.get_settings()
    later = config.Settings(**{**real.__dict__, "demo_now": datetime(2026, 11, 20, 12, tzinfo=TZ)})
    monkeypatch.setattr(config, "get_settings", lambda: later)
    monkeypatch.setattr(gtfs, "get_settings", lambda: later)
    assert gtfs.feed().version == "4.32"
    assert gtfs.service_ids_on(date(2026, 11, 20)) == {"LV"}


def test_no_feed_info_start_uses_the_calendar_and_early_dates_take_the_first_feed(feeds):
    old, new = feeds
    third = new.parent / "smtt_c.zip"
    tiny_zip(third, "4.33", None, "20261201")                  # no feed_start_date: calendar from 1 Dec
    assert gtfs.feed_path(date(2026, 11, 30)) == new
    assert gtfs.feed_path(date(2026, 12, 1)) == third
    assert gtfs.feed_path(date(2026, 11, 1)) == old            # before every feed: the earliest one
