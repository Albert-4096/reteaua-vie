"""DATEX II v3 SituationPublication (SPEC §6.1 item 13), validated against the official 3.5 XSD."""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from pathlib import Path

import pytest
from lxml import etree

from app.common import state
from app.common.timeutil import parse_iso
from tests.conftest import DATA_DIR, needs_data

PREPARED = ("cl_20261108_16dec", "cl_20261107_e3", "cl_20261102_mocioni")
AT = parse_iso("2026-11-08T12:00:00+02:00")
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


def _xsd_dir() -> Path | None:
    here = Path(__file__).resolve().parents[1] / "fixtures" / "datex" / "xsd-3.5"
    for d in (os.environ.get("DATEX_XSD_DIR"), DATA_DIR / "datex" / "xsd-3.5", here):
        if d and (Path(d) / "DATEXII_3_D2Payload.xsd").is_file():
            return Path(d)
    return None


@pytest.fixture(scope="module")
def schema() -> etree.XMLSchema:
    d = _xsd_dir()
    if d is None:
        pytest.skip("DATEX II 3.5 XSD not downloaded (see backend/fixtures/datex/README.md)")
    return etree.XMLSchema(etree.parse(str(d / "DATEXII_3_D2Payload.xsd"), _PARSER))


def _valid(schema: etree.XMLSchema, data: bytes) -> etree._Element:
    doc = etree.fromstring(data, _PARSER)
    assert schema.validate(doc), "\n".join(str(e) for e in schema.error_log)
    return doc


def _prepared() -> list[dict]:
    out = []
    for cid in PREPARED:
        c = state.read("closures", cid)
        if c is None:
            pytest.skip(f"{cid} not prepared (run make precompute)")
        out.append(c)
    return out


def _ns(tag: str) -> str:
    from app.m7_compliance.datex import NS

    prefix, name = tag.split(":")
    return f"{{{NS[prefix]}}}{name}"


def test_empty_publication_is_valid(schema):
    from app.m7_compliance import datex

    root, skipped = datex.build_publication([], AT)
    doc = _valid(schema, datex.to_bytes(root))
    assert skipped == []
    assert doc.find(_ns("sit:situation")) is None
    assert doc.findtext(f"{_ns('com:publicationCreator')}/{_ns('com:nationalIdentifier')}") == \
        "Rețeaua Vie (demo, UniHack 8)"


@needs_data
def test_prepared_cases_as_published_validate(schema):
    from app.m7_compliance import datex

    closures = _prepared()
    items = [datex.PublishedClosure(c, "2026-11-08T09:41:00+02:00") for c in closures]
    root, skipped = datex.build_publication(items, AT)
    doc = _valid(schema, datex.to_bytes(root))
    assert skipped == []
    situations = doc.findall(_ns("sit:situation"))
    assert [s.get("id") for s in situations] == [c["id"] for c in closures]
    for s, c in zip(situations, closures):
        records = s.findall(_ns("sit:situationRecord"))
        parts = 1 if c["geometry"]["type"] == "LineString" else len(c["geometry"]["coordinates"])
        assert len(records) == parts
        for rec in records:
            spec = rec.find(f"{_ns('sit:validity')}/{_ns('com:validityTimeSpecification')}")
            assert parse_iso(spec.findtext(_ns("com:overallStartTime"))) == parse_iso(c["window"]["start"])
            assert parse_iso(spec.findtext(_ns("com:overallEndTime"))) == parse_iso(c["window"]["end"])
            pos = rec.findtext(f"{_ns('sit:locationReference')}/{_ns('loc:gmlLineString')}/{_ns('loc:posList')}")
            nums = [float(x) for x in pos.split()]
            assert 45.6 < nums[0] < 45.9 and 21.0 < nums[1] < 21.4, "posList is 'lat lon' (EPSG:4326)"
    hero = situations[0].find(_ns("sit:situationRecord"))
    assert hero.findtext(f"{_ns('sit:cause')}/{_ns('sit:causeType')}") == "roadMaintenance"   # tram works
    e3 = situations[1].find(_ns("sit:situationRecord"))
    assert e3.findtext(f"{_ns('sit:cause')}/{_ns('sit:causeType')}") == "constructionWork"


def test_schema_rejects_a_broken_record(schema):
    """The validator is real: dropping a mandatory element fails."""
    from app.m7_compliance import datex

    closure = {"id": "cl_test", "title": {"ro": "Test", "en": "Test"}, "direction": "both",
               "window": {"start": "2026-11-08T10:00:00+02:00", "end": "2026-11-08T18:00:00+02:00"},
               "geometry": {"type": "LineString", "coordinates": [[21.22, 45.75], [21.23, 45.76]]},
               "sourceText": "lucrări", "sourceUrl": None}
    root, _ = datex.build_publication([datex.PublishedClosure(closure, "2026-11-08T09:00:00+02:00")], AT)
    _valid(schema, datex.to_bytes(root))
    broken = copy.deepcopy(root)
    rec = broken.find(f"{_ns('sit:situation')}/{_ns('sit:situationRecord')}")
    rec.remove(rec.find(_ns("sit:complianceOption")))
    assert not schema.validate(etree.fromstring(datex.to_bytes(broken), _PARSER))


@needs_data
def test_feed_lists_published_closures_not_ended(isolated_state, schema):
    from app.m7_compliance import datex

    files = [DATA_DIR / "state" / "closures" / f"{cid}.json" for cid in PREPARED[:2]]   # the real store
    real = [json.loads(f.read_text(encoding="utf-8")) for f in files if f.is_file()]
    if len(real) < 2:
        pytest.skip("prepared cases missing (run make precompute)")
    # write into the temp state: the hero published, E3 published too
    for c in real[:2]:
        state.write("closures", c["id"], {**c, "status": "published"})
        state.write("published", c["id"], {"closureId": c["id"], "alerts": [], "feedUrl": "x", "posters": [],
                                           "publishedAt": "2026-11-08T09:41:00+02:00"})
    at = datetime.fromisoformat("2026-11-12T12:00:00+02:00")   # the hero (8 Nov) has ended, E3 (to 13 Nov) not
    doc = _valid(schema, datex.feed_xml(at))
    ids = [s.get("id") for s in doc.findall(_ns("sit:situation"))]
    assert ids == ["cl_20261107_e3"]
    status = doc.find(f".//{_ns('sit:validity')}/{_ns('com:validityStatus')}").text
    assert status == "active"
