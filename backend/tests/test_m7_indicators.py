"""PMUD / TEN-T indicators (SPEC §6.7): each with its method; AC.1 recounted independently from stop_times."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models.v2 import IndicatorSet
from tests.conftest import needs_data


@needs_data
def test_ac1_matches_an_independent_count_from_stop_times():
    """Recount AC.1 at 07:00 from the raw GTFS tables, without the departure index."""
    from app.common import gtfs
    from app.common.timeutil import gtfs_service_start, local_midnight
    from app.m7_compliance.indicators import ac1, reference_day

    day = reference_day()
    assert day is not None and day.weekday() == 1
    assert gtfs_service_start(day) == local_midnight(day)   # no DST change: GTFS seconds = clock time
    f = gtfs.feed()
    trips = f.trips[f.trips["service_id"].isin(gtfs.service_ids_on(day))]
    st = f.stop_times[f.stop_times["trip_id"].isin(trips["trip_id"])]
    last = st.groupby("trip_id")["stop_sequence"].transform("max")
    dep = st[(st["stop_sequence"] < last) & (st["dep_sec"] >= 7 * 3600) & (st["dep_sec"] < 8 * 3600)]
    dep = dep.merge(trips[["trip_id", "route_id"]], on="trip_id")
    per = dep.groupby(["stop_id", "route_id"]).size()
    expected = {s for (s, _r), n in per.items() if n >= 4}
    got = ac1(day)
    assert got["h07"] == len(expected)
    assert got["total"] == len(f.stops)
    assert max(got["h07"], got["h16"]) <= got["any"] <= got["h07"] + got["h16"]


@needs_data
def test_indicator_set_shape_and_methods():
    from app.m7_compliance.indicators import build_indicators

    s = IndicatorSet.model_validate(build_indicators().model_dump(mode="json"))
    by = {i.code: i for i in s.indicators}
    assert list(by) == ["STOPS_CITY", "STOPS_CITY_SHARE", "RES_400M", "RES_400M_SHARE", "AC1_0700", "AC1_1600",
                        "AC1_ANY", "BIKE_KM", "BIKE_KM_LTS2", "PR_OPTIONS"]
    for i in s.indicators:
        assert i.method.ro and i.method.en and i.unit and i.scope
        if i.unit == "%" and i.value is not None:
            assert 0 <= i.value <= 100
    assert 0 < by["STOPS_CITY"].value <= 890
    assert "GHSL" in by["RES_400M"].method.ro and "nu recensământ" in by["RES_400M"].method.ro
    if by["BIKE_KM"].value is not None:
        assert by["BIKE_KM_LTS2"].value <= by["BIKE_KM"].value
    assert s.provenance and s.provenance[0].source.startswith("SMTT GTFS")


@needs_data
def test_reference_day_is_inside_the_feed():
    from app.common import gtfs
    from app.common.timeutil import parse_iso
    from app.m7_compliance.indicators import reference_day

    first, last = gtfs.coverage()
    d = reference_day(parse_iso("2026-11-08T12:00:00+02:00"))
    assert d is not None and first <= d <= last and d.isoformat() == "2026-11-10"
    assert reference_day(parse_iso(f"{(last + timedelta(days=1)).isoformat()}T12:00:00+02:00")) is None


def test_missing_sources_are_null_not_zero(monkeypatch):
    from app.m7_compliance import indicators as ind

    monkeypatch.setattr(ind, "bike_km", lambda: None)
    monkeypatch.setattr(ind, "park_and_ride_count", lambda: None)
    monkeypatch.setattr(ind, "residents_near_stops", lambda: None)
    try:
        s = ind.build_indicators()
    except Exception as e:   # no GTFS on this machine
        pytest.skip(f"no data: {e}")
    by = {i.code: i for i in s.indicators}
    for code in ("BIKE_KM", "BIKE_KM_LTS2", "PR_OPTIONS", "RES_400M", "RES_400M_SHARE"):
        assert by[code].value is None
