"""R23 feeds and R24 helpers on a synthetic closure."""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.analytics import balance, navfeed

CLOSURE = {"id": "cl_x", "title": {"ro": "Lucrări Strada Test", "en": "Works"}, "kind": "notice",
           "window": {"start": "2026-11-02T00:00:00+02:00", "end": "2026-12-31T00:00:00+02:00"},
           "geometry": {"type": "LineString", "coordinates": [[21.2, 45.7], [21.21, 45.71]]},
           "temporaryRoutes": [{"shortName": "4b", "mode": "bus", "streets": ["Strada A", "Strada B"]}],
           "sourceUrl": "https://example.org/notice"}


def test_cifs_is_one_incident_per_line_with_lat_lon_polyline(monkeypatch):
    monkeypatch.setattr(navfeed, "published_closures", lambda active_only=True: [SimpleNamespace(closure=CLOSURE, published_at="2026-11-01T10:00:00+02:00")])
    doc, notes = navfeed.cifs()
    inc = doc["incidents"][0]
    assert inc["type"] == "ROAD_CLOSED" and inc["id"] == "cl_x" and not notes
    assert inc["polyline"] == "45.700000 21.200000 45.710000 21.210000"      # lat lon order
    assert "Strada A → Strada B" in inc["description"]
    json.dumps(doc)


def test_closure_without_line_geometry_is_left_out_with_a_note(monkeypatch):
    c = {**CLOSURE, "geometry": {"type": "Point", "coordinates": [21.2, 45.7]}}
    monkeypatch.setattr(navfeed, "published_closures", lambda active_only=True: [SimpleNamespace(closure=c, published_at="x")])
    doc, notes = navfeed.cifs()
    assert doc["incidents"] == [] and "left out" in notes[0]


def test_avoid_streets_without_analysis_says_so(monkeypatch):
    monkeypatch.setattr(navfeed, "published_closures", lambda active_only=True: [SimpleNamespace(closure=CLOSURE, published_at="x")])
    monkeypatch.setattr(navfeed.jobs, "cached", lambda key: None)
    doc, notes = navfeed.avoid_streets()
    assert [f["properties"]["kind"] for f in doc["features"]] == ["closure"] and "lucru" in notes[0]


def test_balance_figure_defaults_are_null_not_zero():
    f = balance._fig("x", "ro", "en", source="s")
    assert f["value"] is None and f["n"] is None and f["conclusive"] is None


def test_feed_examples_have_the_documented_shape():
    from pathlib import Path

    ex = Path(__file__).resolve().parents[2] / "contract" / "examples" / "v2"
    cifs = json.loads((ex / "waze-cifs.json").read_text(encoding="utf-8"))
    assert all(i["type"] == "ROAD_CLOSED" and i["polyline"] and i["starttime"] for i in cifs["incidents"])
    geo = json.loads((ex / "avoid-streets.json").read_text(encoding="utf-8"))
    assert geo["type"] == "FeatureCollection" and {f["properties"]["kind"] for f in geo["features"]} <= {"closure", "avoid"}
