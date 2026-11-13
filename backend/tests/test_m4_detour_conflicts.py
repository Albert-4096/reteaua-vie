"""shared_detour conflicts (SPEC §6.1 item 10) on the real prepared cases.

Needs the detour loads of the prepared cases in the job cache (make precompute, or
tests/test_m4_detour.py which computes them).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import DATA_DIR, needs_data

from app.common import state

pytestmark = [needs_data,
              pytest.mark.skipif(not (DATA_DIR / "osm" / "timisoara.osm.pbf").is_file(), reason="no OSM extract")]

HERO, MOCIONI = "cl_20261108_16dec", "cl_20261102_mocioni"


@pytest.fixture(scope="module", autouse=True)
def warmed():
    from app.m4_access import detour

    for cid in (HERO, MOCIONI):
        if state.read("closures", cid) is None:
            pytest.skip("prepared cases not built (make precompute)")
        detour.compute_for(cid)


def test_hero_and_mocioni_share_a_detour():
    from app.m1_disruption import conflicts as cf

    items, notes = cf.conflicts_with_notes(HERO)
    kinds = {(c.otherClosureId, c.kind) for c in items}
    assert (MOCIONI, "same_corridor") in kinds          # unchanged behaviour
    assert (MOCIONI, "shared_detour") in kinds
    shared = next(c for c in items if c.otherClosureId == MOCIONI and c.kind == "shared_detour")
    assert shared.stopIds == [] and shared.routeIds
    assert shared.overlap.start == "2026-11-08T10:00:00+02:00"
    assert notes.isascii() and "shared_detour" in notes


def test_symmetric():
    from app.m1_disruption import conflicts as cf

    a = {c.otherClosureId for c in cf.conflicts_for(HERO) if c.kind == "shared_detour"}
    b = {c.otherClosureId for c in cf.conflicts_for(MOCIONI) if c.kind == "shared_detour"}
    assert MOCIONI in a and HERO in b


def test_modified_copy_does_not_use_the_stored_detour():
    """A scenario's in-memory copy with another geometry is not compared (no stale result)."""
    from app.m1_disruption import conflicts as cf

    closure = dict(state.read("closures", HERO))
    closure["geometry"] = {"type": "LineString", "coordinates": [[21.20, 45.74], [21.201, 45.741]]}
    unchecked: list[str] = []
    items = cf.find_conflicts(closure, state.list_all("closures"), unchecked)
    assert not [c for c in items if c.kind == "shared_detour"]
    assert MOCIONI in unchecked


def test_api_header():
    from app.main import app

    r = TestClient(app).get(f"/api/closures/{HERO}/conflicts")
    assert r.status_code == 200
    assert "shared_detour" in r.headers["X-Notes"]
    assert any(c["kind"] == "shared_detour" for c in r.json())
