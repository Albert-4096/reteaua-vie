"""Wordings the notice parser misread without saying so (found on 15 Nov by running it on the 20 recorded
STPT notices and on 12 hand-written ones). Each is now read, or handed to the person as an unread sentence."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.config import TZ
from conftest import needs_data

pytestmark = needs_data

REF = datetime(2026, 11, 15, 10, 0, tzinfo=TZ)   # the day the notice is pasted: „de mâine” = 16 Nov


def _parse(text: str):
    from app.m1_disruption.parser import parse_detail

    return parse_detail(text, reference=REF)


def _window(text: str) -> tuple[str, str, bool]:
    w = _parse(text).window
    return w.start.isoformat()[:16], w.end.isoformat()[:16], w.open_end


def _drawn(d):
    from shapely.geometry import shape

    return shape(d.closure.model_dump(mode="json", by_alias=True)["geometry"])


def _suspended(d) -> set[str]:
    from app.common.city import load_network

    names = {s["id"]: s["name"] for s in load_network().stops}
    return {names[s] for a in d.closure.routeActions or [] for s in a.suspendedStopIds or []}


def test_10872_the_closed_street_is_the_one_named_not_the_first_cross_street():
    """„pe strada Martir Cornel Popescu, pe tronsonul cuprins între străzile Calistrat Hogaș și Nicolae Tincu
    Velea”: the register writes the street with „(1918)”, and one „străzile” covers both cross streets."""
    from app.common.geo import length_m
    from app.common.stpt_posts import get_post
    from app.m1_disruption.parser import parse_detail

    p = get_post(10872)
    if p is None:
        pytest.skip("STPT post 10872 not recorded")
    d = parse_detail(p.text, reference=p.date)
    assert [s.name for s in d.closure_streets] == ["Strada Martir Cornel Popescu (1918)", "Strada Calistrat Hogaș",
                                                   "Strada Nicolae Tincu Velea"]
    assert [s.name for s in d.section] == ["Strada Calistrat Hogaș", "Strada Nicolae Tincu Velea"]
    assert d.closure.title.ro.startswith("Anunț STPT: Strada Martir Cornel Popescu (1918) · linia 21")
    assert 40 < length_m(_drawn(d)) < 200     # the section, not the whole street


@pytest.mark.parametrize("hours, end", [
    ("în intervalul orar 10 00 – 18 00", "2026-11-21T18:00"),
    ("în intervalul orar 10:00 – 18:00", "2026-11-21T18:00"),
    ("între orele 10:00 și 18:00", "2026-11-21T18:00"),
])
def test_days_with_the_hours_of_each_day(hours, end):
    text = f"În perioada 17–21 noiembrie 2026, {hours}, pe Calea Bogdăneștilor se execută lucrări de reparații."
    assert _window(text) == ("2026-11-17T10:00", end, False)


def test_night_hours_over_several_days_end_the_next_morning():
    text = "În perioada 17–21 noiembrie 2026, între orele 22:00 și 05:00, pe Calea Bogdăneștilor se execută lucrări."
    assert _window(text) == ("2026-11-17T22:00", "2026-11-22T05:00", False)


def test_an_hour_on_each_day_is_still_read_as_before():
    text = ("Circulația va fi închisă pe Strada Ardealului, în perioada 07 noiembrie 2026, ora 04:00 – "
            "12 noiembrie 2026, ora 24:00.")
    assert _window(text) == ("2026-11-07T04:00", "2026-11-13T00:00", False)


def test_de_maine_has_no_end_and_the_day_of_tomorrow_is_one_day():
    assert _window("De mâine se închide circulația rutieră pe Strada Ardealului, pentru lucrări.")[::2] == (
        "2026-11-16T00:00", True)
    assert _window("În cursul zilei de mâine se închide circulația rutieră pe Strada Ardealului, pentru lucrări.") == (
        "2026-11-16T00:00", "2026-11-17T00:00", False)


@pytest.mark.parametrize("sentence", [
    "autobuzele liniei Expres 3 nu vor mai opri în stațiile Baba Novac și Canton CFR.",
    "pe linia Expres 3, stațiile Baba Novac și Canton CFR nu vor mai fi deservite.",
])
def test_other_wordings_of_dropped_stops_are_read(sentence):
    d = _parse("În data de 20 noiembrie 2026, din cauza unor lucrări pe Strada Ardealului, " + sentence)
    assert _suspended(d) == {"Baba Novac", "Canton C.F.R."}
    assert d.unread == []


def test_dropped_stops_in_a_wording_with_no_rule_go_to_the_person():
    text = ("În data de 20 noiembrie 2026 se execută lucrări pe Strada Ardealului.\n"
            "Pe linia Expres 3 se anulează oprirea în stația Baba Novac.")
    d = _parse(text)
    assert _suspended(d) == set()
    assert d.unread == ["Pe linia Expres 3 se anulează oprirea în stația Baba Novac."]


def test_a_stop_list_with_no_name_found_goes_to_the_person():
    text = ("În data de 20 noiembrie 2026 se execută lucrări pe Strada Ardealului.\n"
            "Pe linia Expres 3 vor fi suspendate temporar stațiile: Gara Inexistentă, Altă Stație.")
    d = _parse(text)
    assert _suspended(d) == set()
    assert d.unread == ["Pe linia Expres 3 vor fi suspendate temporar stațiile: Gara Inexistentă, Altă Stație."]


def test_a_second_closed_street_is_drawn_too():
    one = _parse("În data de 20 noiembrie 2026 se închide circulația pe Strada Ardealului pentru lucrări de reparații.")
    two = _parse("În data de 20 noiembrie 2026 se închide circulația pe Strada Ardealului pentru lucrări de reparații.\n"
                 "În aceeași zi se închide circulația și pe Calea Bogdăneștilor, tot pentru lucrări.")
    assert [s.name for s in two.closure_streets] == ["Strada Ardealului", "Calea Bogdăneștilor"]
    assert _drawn(two).length > _drawn(one).length
    assert two.closure.title.ro.startswith("Anunț STPT: Strada Ardealului")
    assert two.unread == []


def test_a_street_the_vehicles_are_sent_onto_is_not_a_closed_street():
    d = _parse("În data de 20 noiembrie 2026 se închide circulația pe Strada Ardealului pentru lucrări de reparații.\n"
               "Pe durata lucrărilor, traficul va fi deviat pe Calea Bogdăneștilor, care nu va fi închisă.")
    assert [s.name for s in d.closure_streets] == ["Strada Ardealului"]


def test_a_section_with_an_end_not_found_goes_to_the_person():
    text = ("De mâine se închide circulația rutieră pe strada Gheorghe Lazăr, pe tronsonul cuprins între strada "
            "Coriolan Brediceanu și strada Care Nu Există, pentru lucrări de asfaltare.")
    d = _parse(text)
    assert d.closure_streets[0].name == "Strada Gheorghe Lazăr" and d.section is None
    assert d.unread == [text]
