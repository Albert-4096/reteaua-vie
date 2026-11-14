"""R4: decisions on O2 rows (app/live/triage.py) and what they unlock (R2 state, S1 hook).

Runs on the real 14 Nov recording (case_l23) with a temp state dir.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

import pytest

from app.config import TZ
from app.live import missing, triage
from tests.conftest import needs_data
from tests.test_live_missing import SAT_FROM, SAT_TO, needs_sat

WIN = {"start": SAT_FROM, "end": SAT_TO}


def _at(hhmm: str) -> datetime:
    h, m = hhmm.split(":")
    return datetime(2026, 11, 14, int(h), int(m), tzinfo=TZ)


def _decide(client, route, decision, reason=None, who="dispecer STPT", window=WIN):
    return client.patch(f"/api/live/missing/{route}",
                        json={"window": window, "decision": decision, "reason": reason, "who": who})


@needs_data
@needs_sat
def test_confirm_sets_the_cityapp_state_and_the_log(client, isolated_state):
    r = _decide(client, "R_AB_23", "confirmat")
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["rowState"], d["tripsInService"], d["caseId"], d["reason"]) == ("fara_vehicul", 19, "case_l23", None)

    row = next(x for x in client.get("/api/live/missing", params={"case": "case_l23"}).json()["routes"]
               if x["routeId"] == "R_AB_23")
    assert row["decision"]["decision"] == "confirmat" and row["repeatedDays"] == 1

    # R2: the CityApp feed state, only for the confirmed row, during the window and after it while still absent
    lines = {x["routeId"]: x for x in client.get("/api/lines/status", params={"at": "2026-11-14T09:20:00+02:00"})
             .json()["lines"]}
    l23 = lines["R_AB_23"]
    assert l23["state"] == "fara_vehicul" and l23["since"] == SAT_FROM
    assert l23["label"]["ro"] == "fără vehicul în datele live (neconfirmat de STPT)"
    assert "dispecer STPT" in l23["source"] and "motiv: necunoscut" in l23["source"]
    assert lines["R_TB_11"]["state"] == "normala"  # a partial row nobody confirmed stays normal

    # S1 hook
    gap = missing.confirmed_gap("R_AB_23", _at("09:20"))
    assert set(gap) == {"since", "note"} and gap["since"] == SAT_FROM
    assert missing.confirmed_gap("R_AB_23", _at("05:00")) is None
    assert missing.confirmed_gap("R_AB_23", _at("10:50")) is not None   # still no vehicle after the window
    assert missing.confirmed_gap("R_AB_23", _at("17:00")) is None       # beyond CONTINUE_MAX

    text = client.get("/api/live/missing/log.csv", params={"month": "2026-11"}).text
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";"))
    assert rows[0][0] == "decis_la" and len(rows) == 2
    assert rows[1][1:3] == ["23", "R_AB_23"] and rows[1][8:11] == ["confirmat", "necunoscut", "dispecer STPT"]
    assert "curse neefectuate" not in text


@needs_data
@needs_sat
def test_reject_and_dont_know_never_reach_cityapp(client, isolated_state):
    assert _decide(client, "R_AB_23", "confirmat").status_code == 200
    assert _decide(client, "R_AB_23", "respins", reason="gol_date").status_code == 200
    assert triage.confirmed_gaps(_at("09:20")) == {}
    assert _decide(client, "R_TB_11", "nu_stiu").status_code == 200
    lines = {x["routeId"]: x for x in client.get("/api/lines/status", params={"at": "2026-11-14T09:20:00+02:00"})
             .json()["lines"]}
    assert lines["R_AB_23"]["state"] == "normala" and lines["R_TB_11"]["state"] == "normala"
    assert len(triage.journal()) == 3  # the journal keeps every decision
    rows = list(csv.reader(io.StringIO(client.get("/api/live/missing/log.csv?month=2026-11").text.lstrip("﻿")),
                           delimiter=";"))
    assert [r[8] for r in rows[1:]] == ["confirmat", "respins", "nu știu"]
    assert rows[2][9] == "gol în date"


@needs_data
@needs_sat
@pytest.mark.parametrize("route,body,code", [
    ("R_TV_1", {}, 409),                                                       # not flagged in that window
    ("R_AB_23", {"who": "x"}, 422),                                            # a role, at least 2 characters
    ("R_AB_23", {"decision": "anulat"}, 422),                                  # unknown decision
    ("R_AB_23", {"window": {"start": "2030-01-01T06:00:00+02:00", "end": "2030-01-01T07:00:00+02:00"}}, 422),
])
def test_bad_decisions_are_refused(client, isolated_state, route, body, code):
    payload = {"window": WIN, "decision": "confirmat", "reason": None, "who": "dispecer STPT", **body}
    assert client.patch(f"/api/live/missing/{route}", json=payload).status_code == code
    assert triage.journal() == []


@needs_data
def test_log_month_is_checked(client, isolated_state):
    assert client.get("/api/live/missing/log.csv", params={"month": "2026-13"}).status_code == 422
    text = client.get("/api/live/missing/log.csv", params={"month": "2026-10"}).text
    assert text.lstrip("﻿").count("\n") == 1  # header only
