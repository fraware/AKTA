"""Tests for eval utilities."""

from pathlib import Path

from evals.before_after import compare_evaluations
from evals.graders import FAILURE_TAXONOMY, classify_failure, grade_report
from evals.metrics import compute_metrics
from evals.run_scenarios import run_scenario_eval

ROOT = Path(__file__).resolve().parent.parent


def test_failure_taxonomy_has_f1_f15() -> None:
    for i in range(1, 16):
        key = f"F{i}_"
        assert any(k.startswith(key) for k in FAILURE_TAXONOMY)


def test_grade_report_adds_failure_modes() -> None:
    report = run_scenario_eval(
        ROOT / "scenarios" / "canonical_5.jsonl",
        ROOT / "scenarios" / "expected_decisions.jsonl",
        ROOT / "policy",
        ROOT / "overlays",
    )
    graded = grade_report(report)
    assert "failure_taxonomy_counts" in graded
    assert len(graded["results"]) == 5


def test_compute_metrics_fields() -> None:
    report = run_scenario_eval(
        ROOT / "scenarios" / "canonical_5.jsonl",
        ROOT / "scenarios" / "expected_decisions.jsonl",
        ROOT / "policy",
        ROOT / "overlays",
    )
    metrics = compute_metrics(report)
    for key in ("accuracy", "overreach", "overblocking", "record_completeness", "helpful_boundedness"):
        assert key in metrics


def test_before_after_same_policy() -> None:
    report = run_scenario_eval(
        ROOT / "scenarios" / "canonical_5.jsonl",
        ROOT / "scenarios" / "expected_decisions.jsonl",
        ROOT / "policy",
        ROOT / "overlays",
    )
    comparison = compare_evaluations(report, report)
    assert comparison["net_improvement"] == 0
    assert len(comparison["regressed"]) == 0


def test_classify_failure_f11() -> None:
    code = classify_failure(
        {"failure_mode": "F11_overblocking_useful_assistance"},
        {"passed": False, "actual": {"admissibility": "blocked"}, "expected": {"admissibility": "allowed_with_logging"}},
    )
    assert code == "F11_overblocking_useful_assistance"
