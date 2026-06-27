"""Taxonomy and before/after eval coverage (v0.2)."""

from __future__ import annotations

from pathlib import Path

from evals.before_after import run_before_after
from evals.graders import FAILURE_TAXONOMY, failure_mode_from_scenario
from evals.run_scenarios import run_scenario_eval

ROOT = Path(__file__).resolve().parent.parent


def test_public_100_failure_taxonomy_coverage() -> None:
    report = run_scenario_eval(
        ROOT / "scenarios" / "public_100.jsonl",
        ROOT / "scenarios" / "expected_decisions.jsonl",
        ROOT / "policy",
        ROOT / "overlays",
    )
    counts = report.get("failure_taxonomy_counts", {})
    represented = {code for code in FAILURE_TAXONOMY if code in counts}
    # F8 is reserved for invalid/policy tampering fixtures (test_invalid_cases)
    expected_present = {k for k in FAILURE_TAXONOMY if k != "F8_policy_tampering"}
    missing = expected_present - represented
    assert not missing, f"Missing failure classes in public_100: {missing}"
    f11_count = counts.get("F11_overblocking_useful_assistance", 0)
    assert f11_count >= 20


def test_failure_mode_from_scenario_id() -> None:
    assert failure_mode_from_scenario({"scenario_id": "public_20_f11_literature_search"}) == (
        "F11_overblocking_useful_assistance"
    )
    assert failure_mode_from_scenario({
        "scenario_id": "public_01_f1_priority_weak",
        "failure_mode": "F1_weak_evidence_escalation",
    }) == "F1_weak_evidence_escalation"


def test_before_after_public_100_same_policy() -> None:
    result = run_before_after(
        ROOT / "scenarios" / "public_100.jsonl",
        ROOT / "scenarios" / "expected_decisions.jsonl",
        ROOT / "policy",
        ROOT / "policy",
        ROOT / "overlays",
    )
    comparison = result["comparison"]
    assert comparison["net_improvement"] == 0
    assert len(comparison["regressed"]) == 0
    assert result["before"]["passed"] is True
    assert result["after"]["passed"] is True
