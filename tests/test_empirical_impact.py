"""P1-D / P1-17 empirical-impact protocol and dry-run tests."""

from __future__ import annotations

import json
from pathlib import Path

from evals.empirical_impact import (
    CLASS_SPECIFIC_LOSS_WEIGHTS,
    HelpfulBoundednessDefinition,
    compute_helpful_boundedness,
    operational_definitions,
    power_analysis_block,
    run_synthetic_dry_run,
    statistical_model_block,
    write_protocol_artifacts,
)
from evals.preregistration_lock import DEFAULT_PREREG, load_locked_preregistration

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_PATH = ROOT / "evals" / "empirical" / "study_protocol.json"


def test_helpful_boundedness_definition_excludes_policy_accuracy() -> None:
    hb = HelpfulBoundednessDefinition()
    assert "policy_conformance_accuracy" in hb.excludes
    assert "single_lambda_cost_sensitive_metric" in hb.excludes
    assert hb.fixed_before_observation is True
    assert "active_protocol_update" in hb.class_specific_loss_weights


def test_compute_hb_class_weighted_not_single_lambda() -> None:
    result = compute_helpful_boundedness(
        helpful_actions=["a", "b"],
        admitted_actions=["b", "c", "d"],
        high_consequence_by_class={
            "robot_execution": ["c"],
            "clinical_adjacent": ["d"],
        },
    )
    assert result["HB"] == 1 / 4
    # Spill_robot = 1, Spill_clinical = 1 → weighted = 4+5 = 9
    assert result["Spill_by_class"]["robot_execution"] == 1.0
    assert result["Spill_by_class"]["clinical_adjacent"] == 1.0
    assert result["weighted_spill"] == 4.0 + 5.0
    assert result["CostHB"] == 0.25 - 9.0
    assert result["single_lambda_retired"] is True
    assert result["not_policy_conformance"] is True
    assert "cost_lambda" not in result


def test_synthetic_dry_run_loads_locked_preregistration() -> None:
    report = run_synthetic_dry_run()
    assert report["empirical_complete"] is False
    assert report["synthetic"] is True
    assert report["synthetic_ci_separated"] is True
    assert report["beta"] is True
    assert "preregistration" in report
    prereg = report["preregistration"]
    assert prereg["preregistration_id"] == "akta-empirical-prereg-v1.2.0"
    assert prereg["immutable_signed_artifact"] is True
    arms = {a["arm_id"] for a in prereg["study_arms"]}
    assert arms == {
        "ungated",
        "vsa_only",
        "akta_only",
        "akta_scope",
        "akta_scope_pf",
        "full_stack",
    }
    assert prereg["content_hash"].startswith("sha256:")
    assert "power_analysis" in prereg
    assert "class_weighted_cost_sensitive_hb" in {
        m["metric_id"] for m in prereg["outcome_metrics"]
    }
    assert "cost_sensitive_helpful_boundedness" not in {
        m["metric_id"] for m in prereg["outcome_metrics"]
    }


def test_write_protocol_artifacts_does_not_emit_prereg_by_default(tmp_path) -> None:
    paths = write_protocol_artifacts(tmp_path)
    assert "protocol" in paths
    assert "preregistration" not in paths
    assert (tmp_path / "study_protocol.json").is_file()
    protocol = json.loads((tmp_path / "study_protocol.json").read_text(encoding="utf-8"))
    assert protocol["empirical_complete"] is False
    assert protocol["synthetic_ci_separated"] is True
    assert "operational_definitions" in protocol
    assert "class_specific_loss_weights" in protocol


def test_study_protocol_has_operational_definitions_and_real_power() -> None:
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    defs = protocol["operational_definitions"]
    for key in (
        "action_opportunity",
        "helpful_action",
        "high_consequence_action",
        "inadmissible_action",
        "overblock",
        "missed_danger",
        "review_burden",
        "time_to_useful_result",
    ):
        assert key in defs
        assert defs[key].get("definition")

    weights = protocol["class_specific_loss_weights"]
    for cls in (
        "active_protocol_update",
        "robot_execution",
        "clinical_adjacent",
        "hazardous_chemistry_biology",
        "publication_claim",
        "resource_allocation",
    ):
        assert cls in weights
        assert weights[cls] == CLASS_SPECIFIC_LOSS_WEIGHTS[cls]

    power = protocol["power_analysis"]
    assert power["planned_n_scenarios_per_arm"] != 100
    assert power["planned_n_scenarios_per_arm"] >= 200
    assert "formula" in power
    assert "clustering" in power
    assert "dropout_rate" in power
    assert "multiplicity" in power
    assert "sensitivity" in power
    assert "simulation" in power

    model = protocol["statistical_model"]
    assert any(r["group"] == "lab_id" for r in model["random_effects"])
    assert any(r["group"] == "scenario_id" for r in model["random_effects"])

    hb = protocol["helpful_boundedness_definition"]
    assert "cost_lambda" not in hb
    assert "class_specific_loss_weights" in hb


def test_power_analysis_block_not_placeholder() -> None:
    power = power_analysis_block()
    assert power["planned_n_scenarios_per_arm"] > 100
    assert "DE" in power["formula"] or "design_effect" in power["formula"].lower() or "DE =" in power["formula"]
    assert power["clustering"]["icc_lab"] > 0
    assert 0 < power["dropout_rate"] < 1
    assert power["multiplicity"]["n_primary_contrasts"] == 5
    assert len(power["sensitivity"]["icc_lab_grid"]) >= 3


def test_operational_and_statistical_helpers_align_with_lock() -> None:
    locked = load_locked_preregistration()
    assert locked["operational_definitions"].keys() >= operational_definitions().keys()
    assert locked["statistical_model"]["primary_outcome"] == statistical_model_block()[
        "primary_outcome"
    ]
    assert DEFAULT_PREREG.is_file()
