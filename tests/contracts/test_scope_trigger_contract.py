"""SCOPE review trigger contract tests (AKTA v0.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from akta.records import validate_against_schema
from tests.contracts.scope_fixtures import (
    assemble_review_packet,
    extract_scope_fields,
    validate_approval_grant,
    validate_requested_scope,
)

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_trigger_only_packet(gate: AKTAGate) -> None:
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
    trigger = decision.to_dict()["review_trigger"]
    validate_against_schema(trigger, "review_trigger.schema.json")
    validate_requested_scope(trigger)
    packet = assemble_review_packet(trigger)
    assert packet["packet_mode"] == "trigger_only"
    assert packet["trigger"]["requested_scope"] == "active_protocol_update"


def test_record_only_fields(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize batch."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize",
        context=AKTAContext.from_dict({"evidence_state": "E5_internally_replicated_evidence"}),
        deployment_profile="P5_review_gated_experimental_planner",
        domain_overlay="generic_lab_v0",
    )
    record = decision.to_record().to_dict()
    assert record["record_id"]
    assert record["decision"]["admissibility"] == "review_required"


def test_trigger_plus_record_packet(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Create run plan."},
        requested_tool="experiment_planner.create_run_plan",
        requested_action="create_run_plan",
        context=AKTAContext.from_dict({
            "evidence_state": "E5_internally_replicated_evidence",
            "validation_status": "V4_internally_replicated",
        }),
        deployment_profile="P5_review_gated_experimental_planner",
    )
    trigger = decision.to_dict()["review_trigger"]
    record = decision.to_record().to_dict()
    record["review_trigger"] = trigger
    packet = assemble_review_packet(trigger, record)
    assert packet["packet_mode"] == "trigger_plus_record"
    fields = extract_scope_fields(trigger)
    assert fields["akta_decision_id"] == trigger["decision_id"]
    assert fields["requested_scope"] == "single_validation_plan"


def test_id_alias_fields_present(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Draft claim."},
        requested_tool="publication.draft_claim",
        requested_action="draft_claim",
        context=AKTAContext.from_dict({
            "evidence_state": "E5_internally_replicated_evidence",
        }),
        deployment_profile="P5_review_gated_experimental_planner",
    )
    trigger = decision.to_dict()["review_trigger"]
    assert trigger["decision_id"] == trigger["akta_decision_id"]
    assert trigger["source_record_id"] == trigger["akta_record_id"]
    assert trigger["review_trigger_version"] == "0.3"


def test_pinned_fixture_matches_scope_simulator() -> None:
    trigger = json.loads((FIXTURES / "scope_review_trigger_v0.3.json").read_text(encoding="utf-8"))
    validate_requested_scope(trigger)
    fields = extract_scope_fields(trigger)
    assert fields["requested_scope"] == "active_protocol_update"
    assert fields["akta_decision_id"] == trigger["decision_id"]


def test_narrow_draft_grant_boundary() -> None:
    grant = validate_approval_grant(
        granted_scope="protocol_draft",
        requested_scope="active_protocol_update",
        allowed_tools=["protocol_editor.draft_change"],
        blocked_tools=[
            "protocol_editor.update_active_protocol",
            "robot_queue.submit",
        ],
    )
    assert grant["narrow_draft_grant"] is True
    assert grant["scope_covered"] is False

    with pytest.raises(ValueError, match="does not cover"):
        validate_approval_grant(
            granted_scope="protocol_draft",
            requested_scope="robot_queue_submission",
        )
