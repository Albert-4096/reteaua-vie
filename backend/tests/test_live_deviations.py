"""R18: off-route runs (app/live/deviations.py, GET /api/live/deviations).

Real recording of Sat 14 Nov 2026; skips when it is absent. The labelled sample is
repo/eval/deviations/labels-2026-11-14.json (agent labels, not yet checked by a person).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.common.timeutil import parse_iso
from app.live import deviations
from app.models.live_deviations import Deviations
from tests.conftest import DATA_DIR, needs_data

VEH = DATA_DIR / "live" / "vehicles"
needs_sat = pytest.mark.skipif(not all((VEH / f"20261114-{h:02d}.jsonl.gz").is_file() for h in range(4, 11)),
                               reason="no 14 Nov 06:00-13:00 recording")
needs_day = pytest.mark.skipif(not all((VEH / f"20261113-{h:02d}.jsonl.gz").is_file() for h in range(11, 24)),
                               reason="no 13 Nov 13:00-02:00 recording")
LABELS = Path(__file__).resolve().parents[2] / "eval" / "deviations" / "labels-2026-11-13-14.json"
SAT = ("2026-11-14T06:00:00+02:00", "2026-11-14T13:00:00+02:00")


def _detect(a: str, b: str) -> dict:
    return deviations.detect(parse_iso(a), parse_iso(b))


@needs_data
@needs_sat
def test_counts_add_up_and_tram_loops_are_ignored():
    r = _detect("2026-11-14T10:00:00+02:00", "2026-11-14T11:00:00+02:00")
    Deviations.model_validate(r)
    c = r["counts"]
    assert c["runs"] == sum(c[k] for k in ("ignoredGpsLoss", "ignoredOffSchedule", "ignoredStanding",
                                           "ignoredTerminal", "ignoredDepot", "kept"))
    assert c["ignoredTerminal"] >= 15  # tram turning loops at Gara de Nord, P-ța Domășneanu, Shopping City


@needs_data
@needs_sat
def test_tram_7_at_piata_sfanta_maria_is_a_gps_loss_not_a_diversion():
    """On 14 Nov line 7 (direction 1) showed ~300 m along 16 Decembrie past Piața Sfânta Maria on 14 trips,
    then no position for ~10 min, then its own route again: the onboard unit extrapolates when GPS is lost.
    The tram shapes are not the cause: every one lies on the OSM tram rails."""
    r = _detect(*SAT)
    assert not [g for g in r["groups"] if g["routeId"] == "R_TV_7"]
    assert r["counts"]["ignoredGpsLoss"] >= 14
    import numpy as np
    import shapely as sh

    from app.common.geo import project_lonlats
    from app.m1_disruption import parser

    rails = sh.union_all([sh.LineString(project_lonlats(map(tuple, c))) for c in parser.osm_streets().tram if len(c) >= 2])
    f = deviations.gtfs.feed(parse_iso(SAT[0]))
    trams = set(f.routes[f.routes.route_type == "0"].route_id)
    for sid in f.trips[f.trips.route_id.isin(trams)].shape_id.unique():
        line = deviations._shapes(f)[str(sid)]
        worst = max(line.interpolate(d).distance(rails) for d in np.arange(0, line.length, 25))
        assert worst <= 15, (sid, worst)


@needs_data
@needs_sat
def test_a_published_closure_near_the_run_explains_it(monkeypatch):
    base = _detect(*SAT)
    route = base["groups"][0]["routeId"]
    monkeypatch.setattr(deviations, "_published_actions", lambda at: {route: ("cl_test", None)})
    r = _detect(*SAT)
    g = next(x for x in r["groups"] if x["routeId"] == route)
    assert (g["classification"], g["closureId"]) == ("anuntata", "cl_test")
    import shapely as sh

    far = sh.Point(0, 0)  # a closure far away from the run explains nothing
    monkeypatch.setattr(deviations, "_published_actions", lambda at: {route: ("cl_far", far)})
    g = next(x for x in _detect(*SAT)["groups"] if x["routeId"] == route)
    assert g["classification"] == "fara_anunt"


@needs_data
@needs_sat
@needs_day
def test_precision_on_the_labelled_sample():
    doc = json.loads(LABELS.read_text(encoding="utf-8"))
    r = deviations.detect(parse_iso(doc["window"]["start"]), parse_iso(doc["window"]["end"]))
    flagged = {(t["tripId"], t["vehicleId"], t["start"]) for g in r["groups"] for t in g["tracks"]}
    labelled = {(f["tripId"], f["vehicleId"], f["start"]): f["label"] for f in doc["flags"]}
    assert flagged == set(labelled)  # the sample is every flag the detector keeps in that window
    true = sum(1 for k in flagged if labelled[k] == "abatere_reala")
    assert len(flagged) >= 20 and true / len(flagged) >= 0.85
    # notice 10862 (19 Sep) has an open end in another sentence: it must not explain a run in November
    assert not [g for g in r["groups"] if (g["notice"] or {}).get("postId") == 10862]


@needs_data
def test_api_window_checks(client):
    assert client.get("/api/live/deviations", params={"from": "ieri"}).status_code == 422
    assert client.get("/api/live/deviations", params={"from": "2026-11-14T11:00:00+02:00",
                                                      "to": "2026-11-14T10:00:00+02:00"}).status_code == 422


@needs_data
@needs_sat
def test_api_answers(client):
    r = client.get("/api/live/deviations", params={"from": "2026-11-14T10:00:00+02:00", "to": "2026-11-14T11:00:00+02:00"})
    assert r.status_code == 200
    body = r.json()
    assert body["thresholds"]["offRouteMeters"] == 80 and body["thresholds"]["minReports"] == 3
    assert {p["version"] for p in body["provenance"]} >= {"4.31"}


@needs_data
def test_a_gps_gap_is_never_a_deviation():
    """V5: off route needs positive positions away from the shape; missing positions give nothing."""
    import pandas as pd
    import shapely as sh

    f = deviations.gtfs.feed(parse_iso("2026-11-14T10:00:00+02:00"))
    trip = f.trips[f.trips.route_id == "R_TV_7"].iloc[0]
    line = deviations._shapes(f)[str(trip.shape_id)]
    on = [line.interpolate(d) for d in (100, 300, 500, 2500, 2700)]   # positions on the shape, a 30 min gap between
    far = sh.Point(on[0].x + 1000, on[0].y)                            # one lone jump far away: fewer than 3
    pts = on[:3] + [far] + on[3:]
    t0 = parse_iso("2026-11-14T10:00:00+02:00").timestamp()
    times = [t0, t0 + 30, t0 + 60, t0 + 90, t0 + 1890, t0 + 1920]
    df = pd.DataFrame({"t": times, "vid": "v1", "trip": trip.trip_id, "route": "R_TV_7", "dir": int(trip.direction_id),
                       "x": [p.x for p in pts], "y": [p.y for p in pts]})
    assert deviations.find_runs(df, f) == []


@needs_data
def test_depot_pull_out_is_not_an_unannounced_diversion():
    """14 Nov 23:57-00:00 (21:57-22:00 UTC): tram vehicle 1012 left the depot off Regele Carol, tagged with a
    tram 8 trip, and ran on to Dâmbovița where it started line 2. The tram depot has no GTFS stop, so the
    garage-stop test missed it and it showed as a „fara_anunt” deviation on tram 8."""
    if not (VEH / "20261114-21.jsonl.gz").is_file():
        pytest.skip("no 14 Nov 21:00 UTC recording")
    r = _detect("2026-11-14T23:50:00+02:00", "2026-11-15T00:10:00+02:00")
    assert not [t for g in r["groups"] for t in g["tracks"] if t["vehicleId"] == "1012"]
    assert r["counts"]["ignoredDepot"] >= 1
