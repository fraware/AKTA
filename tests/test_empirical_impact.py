"""P1-D empirical-impact protocol and dry-run tests."""

from __future__ import annotations

from evals.empirical_impact import (
    HelpfulBoundednessDefinition,
    compute_helpful_boundedness,
    run_synthetic_dry_run,
    write_protocol_artifacts,
)


def test_helpful_boundedness_definition_excludes_policy_accuracy() -> None:
    hb = HelpfulBoundednessDefinition()
    assert "policy_conformance_accuracy" in hb.excludes
    assert hb.fixed_before_observation is True


def test_compute_hb_not_conformance() -> None:
    result = compute_helpful_boundedness(
        helpful_actions=["a", "b"],
        admitted_actions=["b", "c"],
        high_consequence_actions=["c"],
    )
    assert result["HB"] == 1 / 3
    assert result["Spill"] == 1.0
    assert result["not_policy_conformance"] is True


def test_synthetic_dry_run_does_not_claim_completion() -> None:
    report = run_synthetic_dry_run()
    assert report["empirical_complete"] is False
    assert report["synthetic"] is True
    assert report["synthetic_ci_separated"] is True
    assert report["beta"] is True
    assert "preregistration" in report
    arms = {a["arm_id"] for a in report["preregistration"]["study_arms"]}
    assert arms == {
        "ungated",
        "vsa_only",
        "akta_only",
        "akta_scope",
        "akta_scope_pf",
        "full_stack",
    }
    assert report["preregistration"]["preregistration_hash"].startswith("sha256:")
    assert "power_analysis" in report["preregistration"]
    assert "cost_sensitive_helpful_boundedness" in {
        m["metric_id"] for m in report["preregistration"]["outcome_metrics"]
    }


def test_write_protocol_artifacts(tmp_path) -> None:
    paths = write_protocol_artifacts(tmp_path)
    assert "preregistration" in paths
    assert (tmp_path / "preregistration.json").is_file()
    assert (tmp_path / "study_protocol.json").is_file()
    prereg = __import__("json").loads((tmp_path / "preregistration.json").read_text())
    assert prereg["empirical_complete"] is False
    assert prereg["synthetic_ci_separated"] is True
