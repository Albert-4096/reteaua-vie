"""T8: the poster says when the file was really made (real Bucharest clock), never the demo clock."""

from __future__ import annotations

import io
from datetime import datetime

from app import config
from app.config import TZ
from app.m1_disruption import poster
from tests.conftest import needs_data
from tests.test_m1_outputs import CLOSURE_ID, STOP_MARIA, _analysis, _closure, _store, outputs_state  # noqa: F401


def _text(pdf: bytes) -> str:
    from pypdf import PdfReader

    return " ".join(PdfReader(io.BytesIO(pdf)).pages[0].extract_text().split())


@needs_data
def test_poster_footer_uses_the_real_time_and_the_cache_keeps_it(outputs_state, monkeypatch):  # noqa: F811
    _store(_closure(), _analysis(unsure_decision=True))
    monkeypatch.setattr(config, "real_now", lambda: datetime(2026, 11, 14, 9, 5, tzinfo=TZ))
    first = poster.poster_pdf(CLOSURE_ID, STOP_MARIA)
    flat = _text(first)
    assert "la 14.11.2026 09:05." in flat and "on 14.11.2026 09:05." in flat
    assert "simulat" not in flat and "08.11.2026" not in flat
    # the same poster later: the cached file, with the time it was really made
    monkeypatch.setattr(config, "real_now", lambda: datetime(2026, 11, 14, 9, 30, tzinfo=TZ))
    assert poster.poster_pdf(CLOSURE_ID, STOP_MARIA) == first
