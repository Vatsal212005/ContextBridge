from __future__ import annotations

import json
from pathlib import Path

import pytest

from contextbridge.evaluation import baseline_prediction, score_cases
from contextbridge.telemetry.store import TelemetryStore


def test_benchmark_has_100_unique_cases() -> None:
    path = Path(__file__).resolve().parents[1] / "evals" / "tool_selection.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert len(cases) == 100
    assert len({case["id"] for case in cases}) == 100
    assert all(case["expected_tool"] for case in cases)


def test_scoring_counts_tool_and_parameter_accuracy() -> None:
    cases = [
        {
            "id": "a",
            "prompt": "repo",
            "expected_tool": "get_repository",
            "expected_arguments": {"owner": "acme", "repo": "api"},
            "risk": "read",
            "confirmation_required": False,
        },
        {
            "id": "b",
            "prompt": "close",
            "expected_tool": "close_issue",
            "expected_arguments": {"issue_number": 7},
            "risk": "destructive",
            "confirmation_required": True,
        },
    ]
    predictions = [
        {"id": "a", "actual_tool": "get_repository", "actual_arguments": {"owner": "acme", "repo": "api"}},
        {"id": "b", "actual_tool": "close_issue", "actual_arguments": {"issue_number": 7}},
    ]
    report, rows = score_cases(cases, predictions)
    assert report["tool_selection_accuracy_pct"] == 100.0
    assert report["parameter_accuracy_pct"] == 100.0
    assert report["risk_accuracy_pct"] == 100.0
    assert report["mutation_classification_accuracy_pct"] == 100.0
    assert all(row["tool_correct"] for row in rows)


def test_baseline_routes_destructive_issue_close() -> None:
    pred = baseline_prediction({"id": "x", "prompt": "Close issue #7 in acme/api."})
    assert pred["actual_tool"] == "close_issue"
    assert pred["actual_arguments"]["issue_number"] == 7
    assert pred["actual_arguments"]["owner"] == "acme"


@pytest.mark.asyncio
async def test_evaluation_run_persists(tmp_path) -> None:
    store = TelemetryStore(tmp_path / "contextbridge.db")
    report = {
        "cases": 1,
        "predictions_received": 1,
        "tool_selection_accuracy_pct": 100.0,
        "parameter_accuracy_pct": 100.0,
        "risk_accuracy_pct": 100.0,
        "mutation_classification_accuracy_pct": 100.0,
    }
    rows = [{
        "id": "case-1", "prompt": "x", "expected_tool": "health", "actual_tool": "health",
        "tool_correct": True, "parameter_score": None, "expected_risk": "read", "actual_risk": "read",
        "risk_correct": True, "confirmation_required": False, "mutation_classification_correct": True,
    }]
    run_id = await store.record_evaluation_run(mode="test", benchmark_name="tiny.json", report=report, results=rows)
    latest = await store.get_evaluation_run()
    assert latest is not None
    assert latest["run_id"] == run_id
    assert latest["report"]["tool_selection_accuracy_pct"] == 100.0
    assert len(latest["results"]) == 1
