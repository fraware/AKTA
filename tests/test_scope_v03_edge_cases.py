"""AKTA v0.3 edge-case tests: SCOPE compat, overlays, memory import."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from akta.policy import PolicyBundle
from akta.scope_contract import (
    assemble_review_packet,
    extract_scope_fields,
    resolve_trigger_requested_scope,
    validate_requested_scope,
)
from akta.scope_mapping import resolve_requested_scope
from adapters.pcs.export_artifact import export_pcs_bundle
from akta.records import AKTARecord

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


@pytest.fixture
def scope_config() -> dict:
    return PolicyBundle.from_dir(ROOT / "policy").tool_to_requested_scope


def test_legacy_review_scope_fallback_maps_to_requested_scope() -> None:
    legacy_trigger = {
        "review_trigger_version": "0.2",
        "review_scope": "draft_only",
        "decision_id": "AKTA-DEC-LEG001",
    }
    assert resolve_trigger_requested_scope(legacy_trigger) == "protocol_draft"
    validate_requested_scope(legacy_trigger)
    fields = extract_scope_fields(legacy_trigger)
    assert fields["requested_scope"] == "protocol_draft"


def test_legacy_active_protocol_scope_fallback() -> None:
    legacy_trigger = {"review_scope": "active_protocol", "decision_id": "AKTA-DEC-LEG002"}
    assert resolve_trigger_requested_scope(legacy_trigger) == "active_protocol_update"


def test_scientific_memory_import_scope_mapping(scope_config: dict) -> None:
    scope = resolve_requested_scope(
        scope_config=scope_config,
        requested_tool="scientific_memory.import",
        action_type="A1_retrieval_or_summary",
        overlay=None,
    )
    assert scope == "scientific_memory_import"


def test_scientific_memory_import_gate_emits_requested_scope(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Import validated finding into lab memory."},
        requested_tool="scientific_memory.import",
        requested_action="import_finding",
        context=AKTAContext.from_dict({
            "evidence_state": "E5_internally_replicated_evidence",
            "validation_status": "V4_internally_replicated",
        }),
        deployment_profile="P5_review_gated_experimental_planner",
    )
    d = decision.to_dict()
    assert d["admissibility"] == "review_required"
    trigger = d["review_trigger"]
    assert trigger["requested_scope"] == "scientific_memory_import"
    assert trigger["review_trigger_version"] == "0.3"
    assert "review_scope" not in trigger


def test_overlay_hazard_trigger_blocks_uncapped_pressure(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Submit run with pressure vessel batch."},
        requested_tool="robot_queue.submit",
        requested_action="submit_run",
        context=AKTAContext.from_dict({
            "evidence_state": "E6_independently_reproduced_evidence",
            "validation_status": "V5_independently_reproduced",
            "metadata": {"hazard_flags": ["uncapped_pressure_vessel"]},
        }),
        deployment_profile="P6_authorized_closed_loop_lab_agent",
        domain_overlay="generic_lab_v0",
    )
    assert decision.admissibility == "blocked"


def test_overlay_hazard_trigger_authorization_for_pyrophoric(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Submit pyrophoric reagent run."},
        requested_tool="robot_queue.submit",
        requested_action="submit_run",
        context=AKTAContext.from_dict({
            "evidence_state": "E6_independently_reproduced_evidence",
            "validation_status": "V5_independently_reproduced",
            "metadata": {"hazard_condition": "pyrophoric_reagent_present"},
        }),
        deployment_profile="P6_authorized_closed_loop_lab_agent",
        domain_overlay="generic_lab_v0",
    )
    assert decision.admissibility == "authorization_required"
    trigger = decision.to_dict()["review_trigger"]
    assert trigger["requested_scope"] == "robot_queue_submission"


def test_overlay_scope_override_materials_robot(scope_config: dict) -> None:
    from akta.overlays import DomainOverlay

    overlay = DomainOverlay.load("materials_v0", ROOT / "overlays")
    assert overlay is not None
    scope = resolve_requested_scope(
        scope_config=scope_config,
        requested_tool="robot_queue.submit",
        action_type="A9_execution_adjacent_or_external_action",
        overlay=overlay,
    )
    assert scope == "robot_queue_submission"


def test_trigger_only_scope_packet_no_record(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Create run plan for next batch."},
        requested_tool="experiment_planner.create_run_plan",
        requested_action="create_run_plan",
        context=AKTAContext.from_dict({
            "evidence_state": "E5_internally_replicated_evidence",
            "validation_status": "V4_internally_replicated",
        }),
        deployment_profile="P5_review_gated_experimental_planner",
    )
    trigger = decision.to_dict()["review_trigger"]
    packet = assemble_review_packet(trigger)
    assert packet["packet_mode"] == "trigger_only"
    assert "record" not in packet
    assert packet["trigger"]["requested_scope"] == "single_validation_plan"


def test_pcs_bundle_includes_scope_review_packet(tmp_path: Path, gate: AKTAGate) -> None:
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
    record = decision.to_record().to_dict()
    record["review_trigger"] = d["review_trigger"]
    scope_packet = assemble_review_packet(d["review_trigger"], record)
    out = export_pcs_bundle(
        AKTARecord(record),
        tmp_path / "pcs",
        decision=d,
        scope_review_packet=scope_packet,
        validate=True,
    )
    manifest = (out / "manifest.json").read_text(encoding="utf-8")
    assert "scope_review_packet.json" in manifest
    assert (out / "scope_review_packet.json").exists()
