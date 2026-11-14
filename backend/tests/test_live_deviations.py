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
LABELS = Path(__file__).resolve().parents[2] / "eval" / "deviations" / "labels-2026-11-14.json"


@needs_data
@needs_sat
def test_ten_to_eleven_counts_and_the_tram_7_run():
    r = deviations.detect(parse_iso("2026-11-14T10:00:00+02:00"), parse_iso("2026-11-14T11:00:00+02:00"))
    Deviations.model_validate(r)
    c = r["counts"]
    assert c["runs"] == c["ignoredOffSchedule"] + c["ignoredStanding"] + c["ignoredTerminal"] + c["ignoredDepot"] + c["kept"]
    assert c["ignoredTerminal"] >= 15  # tram turning loops at Gara de Nord, P-ța Domășneanu, Shopping City
    lines = {(g["shortName"], g["directionId"]): g for g in r["groups"]}
    g7 = lines[("7", 1)]
    assert g7["street"] == "Bulevardul 16 Decembrie 1989" and g7["classification"] == "fara_anunt"
    assert g7["label"]["ro"] == "abatere de la traseu fără anunț găsit de noi — de verificat"
    assert g7["notice"] is None  # notice 11067 names line 7 and the street, but only for 8 Nov 10:00-18:00


@needs_data
@needs_sat
def test_published_closure_explains_a_run(isolated_state, monkeypatch):
    """A run of a line a published closure acts on is „anunțată”, with the closure id."""
    r = deviations.detect(parse_iso("2026-11-14T10:00:00+02:00"), parse_iso("2026-11-14T11:00:00+02:00"))
    monkeypatch.setattr(deviations, "_published_actions", lambda at: {"R_TV_7": "cl_test"})
    r2 = deviations.detect(parse_iso("2026-11-14T10:00:00+02:00"), parse_iso("2026-11-14T11:00:00+02:00"))
    g = next(x for x in r2["groups"] if x["routeId"] == "R_TV_7")
    assert (g["classification"], g["closureId"]) == ("anuntata", "cl_test")
    assert r2["counts"]["announced"] == g["runs"] and r["counts"]["kept"] == r2["counts"]["kept"]


@needs_data
@needs_sat
def test_precision_on_the_labelled_sample():
    doc = json.loads(LABELS.read_text(encoding="utf-8"))
    r = deviations.detect(parse_iso(doc["window"]["start"]), parse_iso(doc["window"]["end"]))
    flagged = {(t["tripId"], t["vehicleId"], t["start"]) for g in r["groups"] for t in g["tracks"]}
    labelled = {(f["tripId"], f["vehicleId"], f["start"]): f["label"] for f in doc["flags"]}
    assert flagged == set(labelled)  # the sample is every flag the detector keeps in that window
    true = sum(1 for k in flagged if labelled[k] == "abatere_reala")
    assert len(flagged) >= 20 and true / len(flagged) >= 0.9


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
