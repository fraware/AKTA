"""Tests for SCOPE-compatible review triggers (v0.3)."""

from __future__ import annotations

import json
from pathlib import Path

from akta import AKTAGate, AKTAContext
from akta.records import validate_against_schema

ROOT = Path(__file__).resolve().parent.parent


def test_review_trigger_schema_validates() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Update active protocol threshold."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_threshold",
        context=AKTAContext.from_dict({
            "evidence_state": "E4_internally_consistent_evidence",
            "validation_status": "V3_preliminary_experimental_support",
        }),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
    )
    d = decision.to_dict()
    assert d.get("review_trigger") is not None
    trigger = d["review_trigger"]
    validate_against_schema(trigger, "review_trigger.schema.json")
    assert trigger["decision_id"] == d["decision_id"]
    assert trigger["akta_decision_id"] == d["decision_id"]
    assert trigger["akta_record_id"] == trigger["source_record_id"]
    assert trigger["review_trigger_version"] == "0.3"
    assert trigger["requested_scope"] == "active_protocol_update"
    assert trigger.get("review_route") == "active_protocol_review"
    assert trigger["policy_hash"].startswith("sha256:")
    assert trigger["review_trigger_hash"].startswith("sha256:")
    assert "blocked_tools" in trigger
    assert "allowed_next_steps" in trigger


def test_review_trigger_export_cli(tmp_path: Path) -> None:
    from akta.cli import main

    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Recommend next step."},
        requested_tool="experiment_planner.create_run_plan",
        requested_action="recommend",
        context=AKTAContext.from_dict({
            "evidence_state": "E5_internally_replicated_evidence",
        }),
        deployment_profile="P5_review_gated_experimental_planner",
    )
    dec_path = tmp_path / "decision.json"
    decision.save(dec_path)
    out_path = tmp_path / "trigger.json"
    rc = main(["review-trigger", "export", "--decision", str(dec_path), "--out", str(out_path)])
    assert rc == 0
    trigger = json.loads(out_path.read_text(encoding="utf-8"))
    validate_against_schema(trigger, "review_trigger.schema.json")
