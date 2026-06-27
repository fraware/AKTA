"""Tests for public_40 scenario evaluation."""

from pathlib import Path

from evals.run_scenarios import run_scenario_eval

ROOT = Path(__file__).resolve().parent.parent


def test_public_40_scenarios_pass() -> None:
    report = run_scenario_eval(
        scenarios_path=ROOT / "scenarios" / "public_40.jsonl",
        expected_path=ROOT / "scenarios" / "expected_decisions.jsonl",
        policy_dir=ROOT / "policy",
        overlays_dir=ROOT / "overlays",
    )
    assert report["passed"] is True, [
        r for r in report["results"] if not r.get("passed")
    ]
    assert report["accuracy"] == 1.0
    assert report["total"] == 40
    assert "metrics" in report
    assert report["metrics"]["helpful_boundedness"] > 0


def test_f11_controls_not_overblocked() -> None:
    report = run_scenario_eval(
        scenarios_path=ROOT / "scenarios" / "public_40.jsonl",
        expected_path=ROOT / "scenarios" / "expected_decisions.jsonl",
        policy_dir=ROOT / "policy",
        overlays_dir=ROOT / "overlays",
    )
    f11_ids = {
        "public_20_f11_literature_search",
        "public_21_f11_hypothesis",
        "public_22_f11_explanation",
        "public_31_validation_draft",
        "public_32_computational_interpret",
        "public_39_handoff_small",
    }
    for r in report["results"]:
        if r["scenario_id"] in f11_ids:
            assert r["passed"], r
            assert r["actual"]["admissibility"] in (
                "allowed",
                "allowed_with_logging",
                "draft_only",
            ), r
