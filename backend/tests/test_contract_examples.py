"""Every file in repo/contract/examples/** validates against its model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from app import models as m
from app.cityapp.models import StopStatus
from app.m1_disruption.notice_text import GeneratedNotice

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
    "v2/tools.json": dict,  # v2.9 (static declarations; the test below checks the shape)
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
