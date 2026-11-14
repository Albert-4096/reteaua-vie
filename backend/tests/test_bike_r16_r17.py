from tests.conftest import needs_data


@needs_data
def test_detour_summary_adds_up_and_says_what_is_unknown():
    from app.m5_bike import bike

    r = bike.bike_impact("cl_20261102_mocioni")
    s = r.detourSummary
    assert s is not None and abs(sum(s.byLts.values()) - s.lengthMeters) < 1.0
    assert set(s.byLts) == {"1", "2", "3", "4", "unknown"}
    assert s.highStressMeters == round(s.byLts["3"] + s.byLts["4"], 1)
    assert s.tramCrossings >= 0 and s.unknownSharePct == 0 and not s.tooLittleData
    assert "traversări de șine" in s.sentence.ro and "LTS 3–4" in s.sentence.ro
    assert "surface" in r.provenance[0].note


@needs_data
def test_short_closure_has_no_detour_to_measure():
    from app.m5_bike import bike

    s = bike.bike_impact("cl_20261108_16dec").detourSummary
    assert s is not None and s.lengthMeters == 0 and "nu există un ocol" in s.sentence.ro


@needs_data
def test_share_alternative_rows_and_none_line():
    from app.m5_bike import bike

    r = bike.bike_impact("cl_20261102_mocioni")
    full = [x for x in r.shareAlternative if x.line]
    assert full and "disponibilitate necunoscută" in full[0].line.ro
    assert full[0].stationFrom.meters <= 400 and full[0].stationTo.meters <= 400 and r.shareNote is None
    e3 = bike.bike_impact("cl_20261107_e3")
    assert not any(x.line for x in e3.shareAlternative)
    assert e3.shareNote.ro == "Nicio stație de bicicletă publică la mai puțin de 400 m de capetele secțiunii."


def test_rough_tags():
    from app.m5_bike.bike import ROUGH_SMOOTHNESS, ROUGH_SURFACES

    assert {"sett", "cobblestone"} <= ROUGH_SURFACES and "bad" in ROUGH_SMOOTHNESS
    assert "asphalt" not in ROUGH_SURFACES and "paving_stones" not in ROUGH_SURFACES
