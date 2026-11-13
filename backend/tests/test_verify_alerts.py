"""Alerts agree with the impact on which stops lose all service (verify run B, T12).

The hero case with the D-012 clerk decisions, built on an in-memory copy of the
stored case: the NO_SERVICE stop alerts are exactly the impact's stopsSuspended.
"""

from __future__ import annotations

from tests.conftest import needs_data
from tests.test_m1_notice_text import HERO, _case, _read, d012_decisions

pytestmark = needs_data


def test_no_service_alerts_equal_impact_suspended_stops():
    from app.m1_disruption import alerts as al
    from app.m1_disruption import impact as imp

    closure, analysis, impact = _case(HERO, d012_decisions(_read(HERO, "analysis")))
    alerts = al.build_alerts(closure, analysis.model_dump(mode="json"))
    stop_alerts = {a.informedEntity[0].stopId: a for a in alerts if a.informedEntity[0].stopId}
    no_service = {s for s, a in stop_alerts.items() if a.effect == "NO_SERVICE"}
    assert "945" in imp.announced_stops(closure)
    assert stop_alerts["945"].effect == "DETOUR"   # line 2 reaches AEM according to the notice
    assert len(no_service) == impact.totals.stopsSuspended
