"""M4 decide: time windows, phasing and v1 compare on the real prepared cases (SPEC §6.4).

The prepared closures are built from the real STPT notices into a temp state dir
(every other DATA_DIR entry is linked), so the real state is never touched.
"""

from __future__ import annotations

import time
from datetime import timedelta

import pytest

from app import config
from app.common.timeutil import parse_iso
from tests.conftest import DATA_DIR, needs_data

pytestmark = needs_data

HERO = "cl_20261108_16dec"
E3 = "cl_20261107_e3"


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    """A temp DATA_DIR with the three prepared closures analyzed (as `make precompute` does)."""
    tmp = tmp_path_factory.mktemp("decide")
    for p in DATA_DIR.iterdir():
        if p.name not in ("state", "cache"):
            (tmp / p.name).symlink_to(p)
    (tmp / "cache").mkdir()
    for p in (DATA_DIR / "cache").iterdir():   # reuse the GTFS index and graphs, but not the job results
        if p.name != "jobs":
            (tmp / "cache" / p.name).symlink_to(p)
    real = config.get_settings()
    fake = config.Settings(env_file=None, data_dir=tmp, live_dir=real.live_dir, demo_now=real.demo_now,
                           data_freeze=False, public_base_url=real.public_base_url)
    mp = pytest.MonkeyPatch()
    mp.setattr(config, "get_settings", lambda: fake)
    import app.common.jobs as jobs_mod
    import app.common.state as state_mod

    mp.setattr(state_mod, "get_settings", lambda: fake)
    mp.setattr(jobs_mod, "get_settings", lambda: fake)
    config.ensure_dirs(fake)
    # access (r5py, a JVM) is the access agent's module and has its own tests; here it is
    # left out so these tests stay fast and run without Java: access is null with a note
    from app.m4_access import scenarios as sc_mod

    mp.setattr(sc_mod, "_access", lambda closure, lost, frequencies: (None, "acces neinclus în test / not run"))
    from app import precompute

    precompute.prepare_cases()
    yield fake
    mp.undo()


def _lost(closure_id):
    from app.common import state
    from app.m4_access.windows import lost_keys

    return lost_keys(state.read("closures", closure_id, "analysis")["stops"])


def test_hero_windows_rank_by_departures_lost(prepared):
    from app.common import gtfs, state
    from app.m4_access import windows as win

    t = time.perf_counter()
    ws = win.suggest(HERO)
    took = time.perf_counter() - t
    print(f"\nhero windows: {took:.2f} s, best {ws.best.start} – {ws.best.end}, "
          f"{ws.candidates[0].departuresLost} departures lost")
    impact = state.read("closures", HERO, "impact")
    assert ws.hours == 8.0                                       # the notice's 10:00–18:00
    assert 1 <= len(ws.candidates) <= 10
    assert [c.rank for c in ws.candidates] == list(range(1, len(ws.candidates) + 1))
    deps = [c.departuresLost for c in ws.candidates]
    assert deps == sorted(deps)
    assert (ws.best.start, ws.best.end) == (ws.candidates[0].window.start, ws.candidates[0].window.end)
    # the platform's best window loses fewer departures than the notice's own window
    assert deps[0] < impact["totals"]["departuresLost"]
    # each figure is a plain timetable count of the lost rows in that window
    keys = _lost(HERO)
    for c in ws.candidates[:3]:
        s, e = parse_iso(c.window.start), parse_iso(c.window.end)
        assert gtfs.count_departures(s, e, keys=keys) == c.departuresLost
        assert s.minute in (0, 30) and e - s == timedelta(hours=8)
    # no two candidates overlap, all start inside the 14 days after DEMO_NOW
    spans = sorted((parse_iso(c.window.start), parse_iso(c.window.end)) for c in ws.candidates)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))
    lo, hi = parse_iso(ws.searchFrom), parse_iso(ws.searchTo)
    assert all(lo <= s <= hi for s, _ in spans) and hi - lo == timedelta(days=14)
    # a closure that overlaps every candidate (Mocioni while it conflicts with the hero, SPEC §5.3)
    # is said once at the top (T5) and not counted on any row
    common = {c.closureId for c in ws.commonConflicts or []}
    assert ws.method.ro.count("Toate ferestrele se suprapun") == (1 if common else 0)
    assert not common & set(ws.method.ro.split("Conflicte numărate cu: ")[-1].rstrip(".").split(", "))
    assert "La aceeași oră ca în anunț" in ws.method.ro and "duminică" in ws.method.ro
    assert ws.provenance and ws.phases is None


def test_phases_get_their_own_non_overlapping_windows(prepared):
    from app.common import gtfs
    from app.common.geo import length_m
    from app.m4_access import windows as win
    from shapely.geometry import shape

    t = time.perf_counter()
    ws = win.suggest(E3, hours=8, phases=2)
    print(f"\nE3 phasing (2): {time.perf_counter() - t:.2f} s")
    assert [p.phase for p in ws.phases] == [1, 2]
    lens = [length_m(shape(p.section.model_dump())) for p in ws.phases]
    assert abs(lens[0] - lens[1]) < 0.02 * max(lens)          # equal length sections
    w = [(parse_iso(p.window.start), parse_iso(p.window.end)) for p in ws.phases]
    assert w[0][1] <= w[1][0] or w[1][1] <= w[0][0]           # phases never overlap in time
    for p, sec in zip(ws.phases, win.split_sections(_geometry(E3), 2)):
        keys = win.section_keys(_closure(E3), sec)
        assert p.departuresLost == gtfs.count_departures(parse_iso(p.window.start), parse_iso(p.window.end),
                                                         keys=keys)
    assert "Etapizare în 2 tronsoane" in ws.method.ro


def _closure(cid):
    from app.common import state

    return state.read("closures", cid)


def _geometry(cid):
    return _closure(cid)["geometry"]


def test_search_range_is_clamped_at_the_timetable_end(prepared):
    from app.m4_access import windows as win

    ws = win.suggest(HERO, hours=8, start="2026-12-28T00:00:00+02:00", end="2027-02-15T00:00:00+02:00")
    assert all(parse_iso(c.window.end) <= parse_iso("2027-01-01T00:00:00+02:00") for c in ws.candidates)
    assert "se termină" in ws.method.ro


def test_bad_inputs(prepared, client):
    r = client.get(f"/api/closures/{HERO}/windows", params={"phases": 5})
    assert r.status_code == 422
    r = client.get("/api/closures/nope/windows")
    assert r.status_code == 404
    r = client.get(f"/api/closures/{HERO}/windows", params={"from": "2027-03-01T00:00:00+02:00",
                                                         "to": "2027-03-10T00:00:00+02:00"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "OUTSIDE_FEED"


def test_windows_endpoint_and_v1_compare(prepared, client):
    r = client.get(f"/api/closures/{HERO}/windows")
    assert r.status_code in (200, 202)
    if r.status_code == 202:
        job = r.json()["jobId"]
        for _ in range(60):
            j = client.get(f"/api/jobs/{job}").json()
            if j["state"] in ("done", "error"):
                break
            time.sleep(0.5)
        assert j["state"] == "done"
    t = time.perf_counter()
    r = client.get(f"/api/closures/{HERO}/windows")          # cached now
    assert r.status_code == 200 and time.perf_counter() - t < 1.0
    assert r.json()["candidates"][0]["rank"] == 1

    r = client.get("/api/compare", params={"a": HERO, "b": E3})
    assert r.status_code == 200
    body = r.json()
    from app.common import state

    assert body["a"]["totals"] == state.read("closures", HERO, "impact")["totals"]
    assert body["b"]["closureId"] == E3


# --- scenarios ------------------------------------------------------------------------------------------


def test_prepared_hero_scenarios_and_compare(prepared, client):
    from app.common import gtfs
    from app.m4_access import scenarios as sc
    from app.m4_access import warm_decide as wd
    from app.m4_access import windows as win

    t = time.perf_counter()
    wd.warm([HERO])
    print(f"\nwarm_decide hero: {time.perf_counter() - t:.1f} s")
    r = client.get("/api/scenarios", params={"closureId": HERO})
    assert r.status_code == 200
    listed = r.json()
    assert [s["id"] for s in listed] == [wd.HERO_L7, wd.HERO_BEST, sc.nothing_id(HERO)]   # prepared first
    assert [s["title"]["ro"] for s in listed] == ["Linia 7 la 6 minute + P&R",
                                                  "Fereastra cea mai bună + pistă temporară", "Nicio măsură"]
    best = win.suggest(HERO).best
    best_mit = next(m for m in listed[1]["mitigations"] if m["kind"] == "window")
    assert (best_mit["start"], best_mit["end"]) == (best.start, best.end)   # the top-ranked window

    t = time.perf_counter()
    r = client.get("/api/scenarios/compare", params={"a": wd.HERO_L7, "b": wd.HERO_BEST})
    took = time.perf_counter() - t
    assert r.status_code == 200 and took < 1.5, took                         # warmed: served from the cache
    a, b = r.json()["a"], r.json()["b"]
    nothing = sc.compute_impact(sc.nothing_id(HERO))
    # frequency never changes the departures lost (a timetable count); it shows as added departures
    assert a["summary"]["departuresLost"] == nothing.summary.departuresLost == nothing.impact.totals.departuresLost
    freq = next(n for n in a["notes"] if n["kind"] == "frequency")
    assert freq["value"] > 0 and "simulare" in freq["text"]["ro"]
    pr = next(n for n in a["notes"] if n["kind"] == "park_and_ride")
    assert "nu modifică cifrele de acces" in pr["text"]["ro"]
    # the best window recounts the impact on its own window: a plain count of the lost rows there
    keys = win.lost_keys(prepared_analysis(HERO)["stops"])
    assert b["summary"]["departuresLost"] == gtfs.count_departures(parse_iso(best.start), parse_iso(best.end),
                                                                    keys=keys)
    assert b["summary"]["departuresLost"] < a["summary"]["departuresLost"]
    assert b["impact"]["window"] == {"start": best.start, "end": best.end}
    # the window ranking and the scenario agree on the residents of that window (same GHSL method)
    assert b["summary"]["residentsLosingStop"] == win.suggest(HERO).candidates[0].residentsLosingStop
    assert any(n["kind"] == "bike_lane" and n["unit"] == "m" for n in b["notes"])
    # never invented: access is either the access module's estimate or null with a note
    for side in (a, b):
        if side["access"] is None:
            assert side["summary"]["residentsLosingAccess"] is None
        else:
            assert side["access"]["estimate"] is True
        assert side["provenance"]


def prepared_analysis(cid):
    from app.common import state

    return state.read("closures", cid, "analysis")


def test_create_scenario_with_segment_and_errors(prepared, client):
    from app.m4_access import scenarios as sc

    closure = prepared_closure(E3)
    coords = closure["geometry"]["coordinates"]
    half = {"type": "LineString", "coordinates": coords[: max(2, len(coords) // 2)]}
    body = {"closureId": E3, "title": {"ro": "Doar jumătate din Ardealului"},
            "mitigations": [{"kind": "segment", "geometry": half}]}
    r = client.post("/api/scenarios", json=body)
    assert r.status_code == 200
    sid = r.json()["id"]
    assert sid.startswith("sc_") and r.json()["createdAt"]
    ids = [s["id"] for s in client.get("/api/scenarios", params={"closureId": E3}).json()]
    assert ids == [sc.nothing_id(E3), sid]                                  # „Nicio măsură” made automatically
    t = time.perf_counter()
    imp = sc.compute_impact(sid)
    print(f"\nE3 segment scenario: {time.perf_counter() - t:.1f} s, {imp.summary}")
    assert any(n.kind == "segment" for n in imp.notes)
    assert imp.impact.closureId == E3 and imp.summary.departuresLost == imp.impact.totals.departuresLost

    bad = dict(body, mitigations=[{"kind": "frequency", "routeId": "R_NOPE", "headwayMinutes": 6}])
    assert client.post("/api/scenarios", json=bad).status_code == 422
    assert client.post("/api/scenarios", json=dict(body, closureId="nope")).status_code == 404
    assert client.get("/api/scenarios/nope/impact").status_code == 404
    assert client.get("/api/scenarios", params={"closureId": "nope"}).status_code == 404


def prepared_closure(cid):
    from app.common import state

    return state.read("closures", cid)
