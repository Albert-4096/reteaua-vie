"""M7 obligations, exports list and the mobilityDCAT-AP NAP catalogue (SPEC §6.7)."""

from __future__ import annotations

import json

from app.m7_compliance import compliance, exports
from app.models.v2 import ComplianceReport, ExportFile

ALL = {f"/api{e.path}" for e in exports.EXPORTS}
SPEC_TABLE = {   # SPEC §6.7: the status of OUR exports per obligation
    "MMTIS": "partial", "RTTI": "covered", "TEN-T": "partial", "AFIR-20": "missing",
    "EPBD-BIKE": "partial", "ROAD-SAFETY": "missing", "AIR-QUALITY": "missing",
    "WEB-ACCESS": "partial",   # R22-B: from our measured axe run (0 violations; an automatic scan is never `covered`)
}
DEADLINES = {   # the team's checked EU deadlines
    "MMTIS": "2025-12-01", "TEN-T": "2027-12-31", "AFIR-20": "2026-04-14", "EPBD-BIKE": "2026-05-29",
    "AIR-QUALITY": "2026-12-11", "RTTI": None, "ROAD-SAFETY": None, "WEB-ACCESS": None,
}


def test_statuses_follow_the_spec_when_every_export_is_served():
    rep = ComplianceReport.model_validate(compliance.report(ALL).model_dump(mode="json"))
    assert {o.id: o.status for o in rep.obligations} == SPEC_TABLE
    assert {o.id: o.deadline for o in rep.obligations} == DEADLINES
    names = {e.name for e in exports.EXPORTS}
    for o in rep.obligations:
        assert set(o.coveredBy) <= names
        assert o.note is not None and o.note.ro and o.note.en
        if o.status in ("covered", "partial") and o.coveredBy:
            assert o.note.ro.startswith("Acoperit de exporturile Rețeaua Vie")
    by_id = {o.id: o for o in rep.obligations}
    assert by_id["RTTI"].coveredBy == ["datex.xml"]
    assert by_id["MMTIS"].coveredBy == ["alerts.pb", "history.json", "nap-metadata.json"]
    assert rep.provenance and "nu este o evaluare" in rep.provenance[0].note.lower()


def test_a_missing_export_is_never_claimed():
    without_datex = ALL - {"/api/feed/datex.xml"}
    by_id = {o.id: o for o in compliance.report(without_datex).obligations}
    assert by_id["RTTI"].status == "missing" and by_id["RTTI"].coveredBy == []
    assert "datex.xml" in by_id["RTTI"].note.ro
    assert "datex.xml" not in {e.name for e in exports.export_files(without_datex)}


def test_counts_add_up():
    c = compliance.counts(ALL)
    assert (c.covered, c.partial, c.missing) == (1, 4, 3)  # + WEB-ACCESS (R22-B)


def test_export_files_have_the_contract_shape(isolated_state):
    files = [ExportFile.model_validate(f.model_dump(mode="json")) for f in exports.export_files(ALL)]
    assert [f.name for f in files] == [e.name for e in exports.EXPORTS]
    assert {f.format for f in files} == {"GTFS-RT", "DATEX II", "JSON", "mobilityDCAT-AP", "NGSI-LD"}
    assert all(f.updatedAt is None for f in files), "nothing published in an empty state: unknown, not a date"
    base = exports.base_url()
    assert all(f.url.startswith(f"{base}/api/") for f in files)


def test_nap_catalog_has_the_four_datasets_and_never_claims_stpt(isolated_state):
    cat = exports.nap_metadata(ALL)
    json.dumps(cat)   # serialisable
    assert cat["@type"] == "dcat:Catalog"
    assert cat["dct:publisher"]["foaf:name"] == "Rețeaua Vie (demo, UniHack 8)"
    ids = [d["dct:identifier"] for d in cat["dcat:dataset"]]
    assert ids == ["alerts.pb", "datex.xml", "notices.json", "history.json"]
    for d in cat["dcat:dataset"]:   # mobilityDCAT-AP mandatory dataset properties
        for key in ("dct:title", "dct:description", "dcat:distribution", "dct:accrualPeriodicity",
                    "dct:spatial", "mobilitydcatap:mobilityTheme", "dct:publisher"):
            assert d.get(key), (d["dct:identifier"], key)
        assert d["mobilitydcatap:mobilityTheme"]["@id"].startswith("https://w3id.org/mobilitydcat-ap/mobility-theme/")
        dist = d["dcat:distribution"][0]
        assert dist["dcat:accessURL"]["@id"].startswith(exports.base_url())
    standards = {d["dct:identifier"]: d["dcat:distribution"][0]["mobilitydcatap:mobilityDataStandard"]["@id"]
                 for d in cat["dcat:dataset"]}
    assert standards["alerts.pb"].endswith("/gtfs-rt") and standards["datex.xml"].endswith("/datex-II")
    assert len(cat["dcat:record"]) == 4
    # one publisher, ours; every dataset says it is not an official STPT / City Hall dataset
    assert {d["dct:publisher"]["@id"] for d in cat["dcat:dataset"]} == {cat["dct:publisher"]["@id"]}
    for d in cat["dcat:dataset"]:
        ro = next(x["@value"] for x in d["dct:description"] if x["@language"] == "ro")
        assert "Nu este un set de date oficial al Primăriei Timișoara sau al STPT" in ro


def test_nap_catalog_drops_a_dataset_that_is_not_served(isolated_state):
    cat = exports.nap_metadata(ALL - {"/api/feed/notices.json"})
    assert [d["dct:identifier"] for d in cat["dcat:dataset"]] == ["alerts.pb", "datex.xml", "history.json"]
