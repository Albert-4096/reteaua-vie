"""R5: km not run and the walk between the cut ends, on the prepared cases (km only, never money)."""

from __future__ import annotations

from app.cityapp import km
from tests.conftest import needs_data


@needs_data
def test_hero_tram_4_km_and_unknown_4b():
    r = km.km_report("cl_20261108_16dec")
    four = [ln for ln in r["lines"] if ln["shortName"] == "4"]
    assert len(four) == 2 and all(6 < ln["sectionKm"] < 12 and ln["trips"] for ln in four)
    assert all(abs(ln["kmNotRun"] - ln["sectionKm"] * ln["trips"]) < 0.2 for ln in four)
    assert r["temporary"][0]["shortName"] == "4b" and r["temporary"][0]["kmRun"] is None
    assert r["temporary"][0]["geometryKm"] and r["temporary"][0]["geometryKm"] > 1
    row = next(x for x in r["rows"] if x["shortName"] == "4")
    assert "Tramvai 4:" in row["text"].ro and "4b: necunoscut" in row["text"].ro and "lei" not in row["text"].ro
    assert any("GTFS" in p.source or "SMTT" in p.source for p in r["provenance"])


@needs_data
def test_e3_has_a_walk_between_the_cut_ends():
    r = km.km_report("cl_20261107_e3")
    w = r["walkBetweenEnds"]
    assert w and all(x["minutes"] >= 1 and x["sentence"].ro.startswith("Pe jos între") for x in w)


@needs_data
def test_endpoint_json_and_csv(client):
    j = client.get("/api/closures/cl_20261107_e3/km").json()
    assert j["notRunByMode"][0]["mode"] == "bus"
    c = client.get("/api/closures/cl_20261107_e3/km", params={"format": "csv"})
    assert c.status_code == 200 and c.text.startswith("﻿inchidere;mod;linie") and ";" in c.text.splitlines()[1]
    assert client.get("/api/closures/nope/km").status_code == 404
