"""R6 on tiny synthetic recordings: no real data, no files from the City Hall API."""

from __future__ import annotations

import gzip
import json

import numpy as np

from app.analytics import accessibility as acc
from app.analytics import recording


def _write(path, snaps):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for s in snaps:
            f.write(json.dumps(s) + "\n")


def _v(vid, trip, route, upd, wc):
    return {"id": vid, "tripId": trip, "routeId": route, "directionId": 0, "updatedAt": upd, "wheelchair": wc}


def test_parse_hour_dedupes_and_votes(tmp_path):
    base = 1_794_000_000  # a Friday afternoon, UTC
    snaps = [
        {"fetchedAt": "2026-11-13T12:00:00+00:00", "vehicles": [_v("a", "t1", "R1", base, True), _v("b", "t2", "R1", base, False)]},
        # same (vehicle, updatedAt): counts once; a new report of the same trip adds a vote
        {"fetchedAt": "2026-11-13T12:00:15+00:00", "vehicles": [_v("a", "t1", "R1", base, True), _v("a", "t1", "R1", base + 20, True),
                                                                _v("c", "t3", "R2", base, None)]},
    ]
    p = tmp_path / "20261113-12.jsonl.gz"
    _write(p, snaps)
    df = recording.parse_hour(p).set_index(["trip", "vid"])
    assert df.loc[("t1", "a"), "n_true"] == 2
    assert df.loc[("t2", "b"), "n_false"] == 1
    assert df.loc[("t3", "c"), "n_null"] == 1


def test_same_trip_id_on_two_days_is_two_trips(tmp_path):
    day = 86400
    base = 1_794_000_000
    p = tmp_path / "20261113-12.jsonl.gz"
    _write(p, [{"fetchedAt": "2026-11-13T12:00:00+00:00",
                "vehicles": [_v("a", "t1", "R1", base, True), _v("a", "t1", "R1", base + day, True)]}])
    assert len(recording.parse_hour(p)) == 2


def test_wait_min_is_the_wait_of_a_random_arrival():
    ts = np.arange(0, 6) * 600.0                     # every 10 min
    assert acc._wait_min(ts) == 5.0
    assert acc._wait_min(ts[:2]) is None             # fewer than MIN_EVENTS
    broken = np.array([0, 600, 1200, 1200 + 5 * 3600.0])  # a 5 h gap is not a wait
    assert acc._wait_min(broken) == 5.0


def test_share_needs_n():
    assert acc._share(0, 0) is None
    assert acc._share(3, 4) == 0.75
