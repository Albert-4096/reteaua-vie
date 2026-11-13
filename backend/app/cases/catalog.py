"""The three prepared demo cases (SPEC §5): descriptions only, no figures.

Every number about a case (stops, departures, residents) is computed by the
M1 pipeline from real data; nothing here is a result. `build.py` (m1-notices)
turns each case into a stored Closure using these ids and windows.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.common.stpt_posts import get_post
from app.models.base import I18n
from app.models.v1 import CaseSummary


@dataclass(frozen=True)
class Case:
    id: str
    closure_id: str
    post_id: int                 # the STPT notice on stpt.ro
    title: I18n
    note: I18n
    date: str                    # first day of the closure, YYYY-MM-DD
    window_start: str            # ISO with offset
    window_end: str              # ISO with offset
    open_end: bool               # True: "până la finalizarea lucrărilor"
    cause: str                   # GTFS-RT cause name
    route_ids: tuple[str, ...]   # lines the notice names (city ids)

    def summary(self) -> CaseSummary:
        return CaseSummary(id=self.id, title=self.title, kind="notice", date=self.date,
                           closureId=self.closure_id, note=self.note)

    def source_url(self) -> str | None:
        post = get_post(self.post_id)
        return post.link if post else None


CASES: tuple[Case, ...] = (
    Case(
        id="case_16dec",
        closure_id="cl_20261108_16dec",
        post_id=11067,
        title=I18n(
            ro="Lucrări la linia de tramvai, Bd. 16 Decembrie 1989, sens Podul Maria",
            en="Tram track works, 16 Decembrie 1989 Blvd, towards Podul Maria",
        ),
        note=I18n(
            ro="Anunț STPT real din 6 nov 2026 (nr. 11067), pentru 8 nov 2026, 10:00–18:00. "
               "Linia 4 suspendată, liniile 2 și 7 scurtate, autobuz temporar 4b.",
            en="Real STPT notice of 6 Nov 2026 (no. 11067), for 8 Nov 2026, 10:00–18:00. "
               "Line 4 suspended, lines 2 and 7 shortened, temporary bus 4b.",
        ),
        date="2026-11-08",
        window_start="2026-11-08T10:00:00+02:00",
        window_end="2026-11-08T18:00:00+02:00",
        open_end=False,
        cause="MAINTENANCE",
        route_ids=("R_TV_4", "R_TV_2", "R_TV_7"),
    ),
    Case(
        id="case_e3",
        closure_id="cl_20261107_e3",
        post_id=11065,
        title=I18n(
            ro="Str. Ardealului închisă, linia E3 deviată",
            en="Ardealului St closed, line E3 diverted",
        ),
        note=I18n(
            ro="Anunț STPT real din 5 nov 2026 (nr. 11065): Str. Ardealului între Str. Rahovei și "
               "Str. Martir Gogu Opre, ambele sensuri, 7 nov 04:00 – 12 nov 24:00.",
            en="Real STPT notice of 5 Nov 2026 (no. 11065): Ardealului St between Rahovei St and "
               "Martir Gogu Opre St, both directions, 7 Nov 04:00 – 12 Nov 24:00.",
        ),
        date="2026-11-07",
        window_start="2026-11-07T04:00:00+02:00",
        window_end="2026-11-13T00:00:00+02:00",
        open_end=False,
        cause="CONSTRUCTION",
        route_ids=("R_AB_E3",),
    ),
    Case(
        id="case_mocioni",
        closure_id="cl_20261102_mocioni",
        post_id=11060,
        title=I18n(
            ro="Lucrări Bd. 16 Decembrie 1989 – Piața Mocioni, linii metropolitane deviate",
            en="Works at 16 Decembrie 1989 Blvd – Mocioni Sq, metropolitan lines diverted",
        ),
        note=I18n(
            ro="Anunț STPT real din 30 oct 2026 (nr. 11060), în vigoare din 2 nov 2026 până la "
               "finalizarea lucrărilor. Liniile M32, M36, M37, M38, M46, M51 (S8 nu e în GTFS). "
               "Vehicule înregistrate de noi din 13 nov 2026.",
            en="Real STPT notice of 30 Oct 2026 (no. 11060), in force from 2 Nov 2026 until the "
               "works end. Lines M32, M36, M37, M38, M46, M51 (S8 is not in the GTFS). "
               "Vehicles recorded by us since 13 Nov 2026.",
        ),
        date="2026-11-02",
        window_start="2026-11-02T00:00:00+02:00",
        window_end="2026-12-31T23:59:59+02:00",
        open_end=True,
        cause="CONSTRUCTION",
        route_ids=("R_AB_M32", "R_AB_M36", "R_AB_M37", "R_AB_M38", "R_AB_M46", "R_AB_M51"),
    ),
)

CASES_BY_ID = {c.id: c for c in CASES}
CASES_BY_CLOSURE = {c.closure_id: c for c in CASES}


def case_summaries() -> list[CaseSummary]:
    return [c.summary() for c in CASES]
