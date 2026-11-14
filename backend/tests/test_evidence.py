"""R13: journal chain, bundle hash and CSV on the prepared cases (read-only)."""

from __future__ import annotations

from app.evidence import journal
from tests.conftest import needs_data

E3 = "cl_20261107_e3"


@needs_data
def test_journal_is_a_chain_that_recomputes():
    j = journal.journal(E3)
    ents = j["entries"]
    assert [e["kind"] for e in ents] == ["publish", "decision"] and j["head"] == ents[-1]["hash"]
    prev = journal.sha(E3)
    for e in ents:
        body = {k: v for k, v in e.items() if k != "hash"}
        assert body["prevHash"] == prev and journal.sha(journal.canon(body)) == e["hash"]
        prev = e["hash"]
    assert all(e["feedVersion"] and e["numbers"]["stopsSuspended"] == 11 for e in ents)
    assert ents[1]["role"] is None


@needs_data
def test_bundle_hash_and_rerun():
    b = journal.bundle(E3, verify=True)
    assert b["verified"] is True
    assert b["sha256"] == journal.sha(journal.canon({"inputs": b["inputs"], "results": b["results"]}))
    assert b == {**journal.bundle(E3, verify=True)}      # deterministic


@needs_data
def test_csv_is_excel_ready(client):
    r = client.get(f"/api/closures/{E3}/impact.csv")
    assert r.status_code == 200 and r.text.startswith("﻿cartier;statii_suspendate;")
    assert r.text.splitlines()[-1].startswith("TOTAL;11;1386;")
    m = client.get("/api/live/missing.csv", params={"case": "case_l23"})
    assert m.status_code == 200 and m.text.splitlines()[0].startswith("﻿mod;curse_in_orar")
    assert client.get(f"/api/closures/{E3}/bundle.json").json()["sha256"]
    assert client.get("/api/closures/nope/journal").status_code == 404
