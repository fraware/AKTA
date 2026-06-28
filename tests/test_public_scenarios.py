"""Tests for public scenario evaluation."""

from pathlib import Path

from evals.run_scenarios import run_scenario_eval

ROOT = Path(__file__).resolve().parent.parent


def test_public_100_scenarios_pass() -> None:
    report = run_scenario_eval(
        scenarios_path=ROOT / "scenarios" / "public_100.jsonl",
        expected_path=ROOT / "scenarios" / "expected_decisions.jsonl",
        policy_dir=ROOT / "policy",
        overlays_dir=ROOT / "overlays",
    )
    assert report["passed"] is True, [
        r for r in report["results"] if not r.get("passed")
    ]
    assert report["accuracy"] == 1.0
    assert report["total"] >= 100
    assert "metrics" in report
    assert "per_failure_class" in report["metrics"]
    assert report["metrics"]["helpful_boundedness"] > 0


def test_f11_controls_not_overblocked() -> None:
    report = run_scenario_eval(
        scenarios_path=ROOT / "scenarios" / "public_100.jsonl",
        expected_path=ROOT / "scenarios" / "expected_decisions.jsonl",
        policy_dir=ROOT / "policy",
        overlays_dir=ROOT / "overlays",
    )
    f11_results = [r for r in report["results"] if "_f11_" in r["scenario_id"]]
    assert len(f11_results) >= 20
    for r in f11_results:
        assert r["passed"], r
        assert r["actual"]["admissibility"] in (
            "allowed",
            "allowed_with_logging",
            "draft_only",
        ), r
