"""Tests for canonical scenario evaluation."""

from pathlib import Path

from evals.run_scenarios import run_scenario_eval

ROOT = Path(__file__).resolve().parent.parent


def test_canonical_five_scenarios_pass() -> None:
    report = run_scenario_eval(
        scenarios_path=ROOT / "scenarios" / "canonical_5.jsonl",
        expected_path=ROOT / "scenarios" / "expected_decisions.jsonl",
        policy_dir=ROOT / "policy",
        overlays_dir=ROOT / "overlays",
    )
    assert report["passed"] is True, report["results"]
    assert report["accuracy"] == 1.0
