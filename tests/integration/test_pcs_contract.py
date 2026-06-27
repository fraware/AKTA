"""PCS export contract integration tests (v0.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from adapters.pcs.export_artifact import export_pcs_bundle
from akta.records import validate_against_schema

ROOT = Path(__file__).resolve().parent.parent.parent


def test_pcs_export_validates_manifest(tmp_path: Path) -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize B."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P2_analysis_assistant",
        domain_overlay="generic_lab_v0",
    )
    record = decision.to_record()
    out = export_pcs_bundle(record, tmp_path / "pcs", decision=decision.to_dict(), validate=True)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    validate_against_schema(manifest, "pcs_akta_artifact.schema.json")
    assert manifest["schema_version"] == "akta-record-v0.2"
    assert (out / "akta_record.json").exists()
    assert (out / "akta_decision.json").exists()


def test_pcs_export_includes_review_trigger(tmp_path: Path) -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Create run plan for replicated batch."},
        requested_tool="experiment_planner.create_run_plan",
        requested_action="create_run_plan",
        context=AKTAContext.from_dict({
            "evidence_state": "E5_internally_replicated_evidence",
            "validation_status": "V4_internally_replicated",
        }),
        deployment_profile="P5_review_gated_experimental_planner",
    )
    d = decision.to_dict()
    assert d.get("review_trigger") is not None
    record = decision.to_record()
    record_data = record.to_dict()
    record_data["review_trigger"] = d["review_trigger"]
    from akta.records import AKTARecord

    out = export_pcs_bundle(AKTARecord(record_data), tmp_path / "pcs", decision=d, validate=True)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert "review_trigger.json" in manifest["files"]
    assert (out / "review_trigger.json").exists()
    trigger = json.loads((out / "review_trigger.json").read_text(encoding="utf-8"))
    validate_against_schema(trigger, "review_trigger.schema.json")


def test_pcs_round_trip_field_names(tmp_path: Path) -> None:
    """Manifest and decision payload use PF-Core/PCS-Core compatible field names."""
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize B."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P2_analysis_assistant",
        domain_overlay="generic_lab_v0",
    )
    d = decision.to_dict()
    record = decision.to_record()
    out = export_pcs_bundle(record, tmp_path / "pcs", decision=d, validate=True)
    exported_decision = json.loads((out / "akta_decision.json").read_text(encoding="utf-8"))
    for field in (
        "decision_id",
        "admissibility",
        "scientific_action_type",
        "responsibility_level",
        "evidence_state",
        "decision_reason",
        "policy_hash",
        "consequentiality",
    ):
        assert field in exported_decision
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact_type"] == "akta_scientific_action_record"
    assert manifest["policy_hash"].startswith("sha256:")
    assert manifest["record_hash"].startswith("sha256:")


def test_pcs_export_missing_policy_hash_fails(tmp_path: Path) -> None:
    bad_record = {
        "record_id": "AKTA-SAR-BAD00001",
        "record_hash": "sha256:abc",
        "classification": {"scientific_action_type": "A0_explanation", "responsibility_level": "R0_informational_assistance", "evidence_state": "E0_no_evidence"},
        "decision": {"admissibility": "allowed", "decision_reason": "test", "blocked_tools": [], "allowed_tools": []},
        "provenance": {"policy_hash": "invalid", "tool_registry_hash": "sha256:abc"},
    }
    with pytest.raises(ValueError, match="policy_hash"):
        export_pcs_bundle(bad_record, tmp_path / "bad", validate=True)
