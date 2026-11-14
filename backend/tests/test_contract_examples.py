"""Every file in repo/contract/examples/** validates against its model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from app import models as m
from app.city_reports.models import AreaReports, RoadIssues
from app.dataquality.models import DataQuality
from app.m1_disruption.events import EventConflicts
from app.feedcheck.models import FeedCheck, FeedDiff
from app.checkin.models import CheckinAck, CheckinCounts
from app.cityapp.models import StopStatus
from app.models.lines_status import LinesStatus
from app.models.live_deviations import Deviations
from app.models.live_missing import MissingLines, TriageDecision
from app.m1_disruption.notice_text import GeneratedNotice
from app.m1_disruption.streets import StreetSearch, StreetSection
from app.observed.models import DetourCost, ObservedSummary
from app.analytics.models import (
    CutThrough, WorksBalance,
    AccessibilityLines, CorridorsResponse, CoverageSummary, CriticalStreetsResponse, ReliabilityResponse,
    StandingResponse, StopAccessibility, VehicleHealthResponse)

EXAMPLES = Path(__file__).resolve().parents[2] / "contract" / "examples"

# example path (relative to contract/examples) -> the type it shows
MODELS: dict[str, object] = {
    "error.json": m.ErrorResponse,
    "provenance.json": m.Provenance,
    "closure-input.json": m.ClosureInput,
    "closure.json": m.Closure,
    "analysis.json": m.Analysis,
    "impact.json": m.Impact,
    "alert.json": m.Alert,
    "publish-result.json": m.PublishResult,
    "live-check.json": m.LiveCheck,
    "cases.json": list[m.CaseSummary],
    "v2/health.json": m.Health,
    "v2/scans.json": m.ScanCounts,
    "v2/data-quality.json": DataQuality,
    "v2/event-conflicts.json": EventConflicts,
    "v2/reports-zones.json": AreaReports,
    "v2/reports-stops.json": AreaReports,
    "v2/road-issues.json": RoadIssues,
    "v2/layer-road-issues.json": m.LayerCollection,
    "v2/feed-diff.json": FeedDiff,
    "v2/feed-check.json": FeedCheck,
    "v2/closure-summary.json": list[m.ClosureSummary],
    "v2/overview.json": m.Overview,
    "v2/layer-bike.json": m.LayerCollection,
    "v2/bike-impact.json": m.BikeImpact,
    "v2/parking-impact.json": m.ParkingImpact,
    "v2/access-impact.json": m.AccessImpact,
    "v2/detour-load.json": m.DetourLoad,
    "v2/conflicts.json": list[m.Conflict],
    "v2/reports.json": m.ReportSummary,
    "v2/windows.json": m.WindowSuggestion,
    "v2/scenario.json": m.Scenario,
    "v2/scenario-impact.json": m.ScenarioImpact,
    "v2/zone-notice.json": list[m.ZoneNotice],
    "v2/route-plan.json": m.RoutePlan,
    "v2/compliance.json": m.ComplianceReport,
    "v2/history.json": list[m.HistoryEntry],
    "v2/indicators.json": m.IndicatorSet,
    "v2/exports.json": list[m.ExportFile],
    "v2/job.json": m.Job,
    "v2/feed-validation.json": m.FeedValidation,  # v2.3
    "v2/generated-notice.json": GeneratedNotice,  # v2.4
    "v2/stop-status.json": StopStatus,  # v2.9
    "v2/km.json": dict,  # v2.13 (R5)
    "v2/timetable-check.json": dict,  # v2.13 (R27)
    "v2/checkin.json": CheckinAck,  # v2.22 (C1)
    "v2/checkins.json": CheckinCounts,  # v2.22 (C1, real response, test sticker = simulare)
    "v2/tools.json": dict,  # v2.9 (static declarations; the test below checks the shape)
    "v2/live-missing.json": MissingLines,  # v2.13 (O2, real response of ?case=case_l23)
    "v2/observed-summary.json": ObservedSummary,  # v2.14 (L0, real response)
    "v2/detour-cost.json": DetourCost,  # v2.22 (L1-B, real response of Mocioni)
    "v2/accessibility-lines.json": AccessibilityLines,  # v2.16 (R6, real response, lines cut to 4)
    "v2/accessibility-stop.json": StopAccessibility,  # v2.16 (R6, real response)
    "v2/layer-accessibility.json": m.LayerCollection,  # v2.16 (R6, real response, features cut to 6)
    "v2/coverage-zones.json": CoverageSummary,  # v2.20 (A10, real response, zones cut to 5)
    "v2/layer-coverage.json": m.LayerCollection,  # v2.20 (A10, real response, features cut to 4)
    "v2/reliability-lines.json": ReliabilityResponse,  # v2.27 (L3, real response, 2 lines, 3 hours each)
    "v2/reliability-vehicles.json": VehicleHealthResponse,  # v2.27 (L3 / A1, real response, 3 vehicles)
    "v2/streets-critical.json": CriticalStreetsResponse,  # v2.27 (R8, real response, 3 sections)
    "v2/layer-streets.json": m.LayerCollection,  # v2.27 (R8, real response, 3 features)
    "v2/cut-through.json": CutThrough,  # v2.30 (R23, real response of the E3 closure)
    "v2/balance.json": WorksBalance,  # v2.30 (R24, real response of Mocioni)
    "v2/waze-cifs.json": dict,  # v2.30 (R23, real response; checked by test_analytics_cutthrough)
    "v2/avoid-streets.json": dict,  # v2.30 (R23, real response)
    "v2/standing.json": StandingResponse,  # v2.27 (L4, real response, 3 points)
    "v2/corridors.json": CorridorsResponse,  # v2.20 (A8, real response, 2 corridors, 4 hours each)
    "v2/lines-status.json": LinesStatus,  # v2.18 (R2, real response of ?since=: hero closure published)
    "v2/live-missing-decision.json": TriageDecision,  # v2.24 (R4, real PATCH response in a scratch state)
    "v2/live-deviations.json": Deviations,  # v2.29 (R18, real response, 14 Nov 10:00-11:00)
    "v2/streets.json": StreetSearch,  # v2.19 (R1-B, real response of ?q=ardealului)
    "v2/street-section.json": StreetSection,  # v2.19 (R1-B, real response: Ardealului, Rahovei -> Martir Gogu Opre)
}


def _example_files() -> list[str]:
    return sorted(str(p.relative_to(EXAMPLES)) for p in EXAMPLES.rglob("*.json"))


def test_every_example_has_a_model():
    missing = [f for f in _example_files() if f not in MODELS]
    assert not missing, f"examples without a model mapping: {missing}"


@pytest.mark.parametrize("name", _example_files())
def test_example_validates(name: str):
    data = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    TypeAdapter(MODELS[name]).validate_python(data)
