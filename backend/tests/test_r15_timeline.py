"""R15-B: the closure lifecycle (Closure.timeline), HistoryEntry.leadHours and the lead-time indicator."""

from __future__ import annotations

from datetime import datetime
from statistics import median

import pytest

from app.config import TZ
from conftest import needs_data

pytestmark = needs_data

HERO = "cl_20261108_16dec"


def _closure(cid: str) -> dict:
    from app.common import state

    c = state.read("closures", cid)
    if c is None:
        pytest.skip(f"{cid} not in the state")
    return c


def test_hero_timeline_steps_come_from_their_sources():
    """11067 went up on 6 Nov 10:26; the works run 8 Nov 10:00–18:00 (the card's QR row)."""
    from app.m1_disruption.timeline import timeline

    t = timeline(_closure(HERO), at=datetime(2026, 11, 8, 12, 0, tzinfo=TZ))
    steps = {s.step: s for s in t.steps}
    assert [s.step for s in t.steps] == ["anuntat", "publicat", "in_desfasurare", "incheiat"]
    assert steps["anuntat"].at == "2026-11-06T10:26:44+02:00" and "11067" in steps["anuntat"].source
    assert (steps["in_desfasurare"].at, steps["incheiat"].at) == ("2026-11-08T10:00:00+02:00", "2026-11-08T18:00:00+02:00")
    assert t.current == "in_desfasurare" and not steps["incheiat"].done
    assert t.leadHours == 47.6                      # 6 Nov 10:26:44 -> 8 Nov 10:00
    before = timeline(_closure(HERO), at=datetime(2026, 11, 6, 9, 0, tzinfo=TZ))
    assert before.current is None


def test_get_closure_carries_the_timeline():
    from fastapi.testclient import TestClient

    from app.main import app

    body = TestClient(app).get(f"/api/closures/{HERO}").json()
    assert body["timeline"]["steps"][0]["step"] == "anuntat"
    assert body["timeline"]["noticeUrl"].startswith("https://stpt.ro/")


def test_no_notice_no_lead_and_an_open_end_says_so():
    from app.m1_disruption.parser import open_end_default
    from app.m1_disruption.timeline import timeline

    c = {"id": "cl_drawn_test", "sourceUrl": None,
         "window": {"start": "2026-11-09T00:00:00+02:00", "end": open_end_default().isoformat()}}
    t = timeline(c, at=datetime(2026, 11, 10, tzinfo=TZ))
    steps = {s.step: s for s in t.steps}
    assert steps["anuntat"].at is None and t.leadHours is None and t.noticeUrl is None
    assert not steps["publicat"].done and t.current == "in_desfasurare"
    assert steps["incheiat"].source.startswith("anunțul nu dă o dată de încheiere")


def test_history_lead_hours_and_the_median_indicator():
    from app.common.timeutil import parse_iso
    from app.m7_compliance.history import history
    from app.m7_compliance.indicators import notice_lead

    rows = [r for r in history() if r.leadHours is not None]
    assert rows
    for r in rows:
        if r.closureId.startswith("stpt_"):   # back-filled: publishedAt is the post time
            hours = (parse_iso(r.window.start) - parse_iso(r.publishedAt)).total_seconds() / 3600
            assert r.leadHours == round(hours, 1)
    leads = {}
    for r in rows:
        leads.setdefault(r.sourceUrl or r.closureId, r.leadHours)
    ind, prov = notice_lead()
    by = {i.code: i for i in ind}
    assert by["NOTICE_LEAD_N"].value == len(leads)
    assert by["NOTICE_LEAD_MEDIAN"].value == round(median(leads.values()), 1)
    assert by["NOTICE_LEAD_MEDIAN"].unit == "h" and prov is not None
