"""Tool-to-requested_scope mapping tests (AKTA v0.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from akta.policy import PolicyBundle
from akta.scope_mapping import VALID_REQUESTED_SCOPES, resolve_requested_scope

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


@pytest.fixture
def scope_config() -> dict:
    return PolicyBundle.from_dir(ROOT / "policy").tool_to_requested_scope


@pytest.mark.parametrize(
    "tool,action_type,expected_scope",
    [
        ("protocol_editor.draft_change", "A5_protocol_modification", "protocol_draft"),
        ("protocol_editor.update_active_protocol", "A5_protocol_modification", "active_protocol_update"),
        ("experiment_planner.create_validation_draft", "A6_experimental_planning", "single_validation_run_draft"),
        ("experiment_planner.create_run_plan", "A6_experimental_planning", "single_validation_plan"),
        ("lab_scheduler.prioritize", "A7_resource_or_queue_prioritization", "single_run_queue_priority"),
        ("workflow.update_state", "A8_tool_or_workflow_mutation", "execution_payload_preparation"),
        ("robot_queue.submit", "A9_execution_adjacent_or_external_action", "robot_queue_submission"),
        ("publication.draft_claim", "A10_publication_or_claim_escalation", "publication_claim"),
    ],
)
def test_requested_scope_mapping(
    scope_config: dict,
    tool: str,
    action_type: str,
    expected_scope: str,
) -> None:
    scope = resolve_requested_scope(
        scope_config=scope_config,
        requested_tool=tool,
        action_type=action_type,
        overlay=None,
    )
    assert scope == expected_scope
    assert scope in VALID_REQUESTED_SCOPES


@pytest.mark.parametrize(
    "tool,action,profile,evidence,expected_scope",
    [
        ("protocol_editor.update_active_protocol", "update_threshold", "P4_protocol_drafting_assistant", "E4_internally_consistent_evidence", "active_protocol_update"),
        ("experiment_planner.create_run_plan", "create_run_plan", "P5_review_gated_experimental_planner", "E5_internally_replicated_evidence", "single_validation_plan"),
        ("lab_scheduler.prioritize", "prioritize", "P5_review_gated_experimental_planner", "E5_internally_replicated_evidence", "single_run_queue_priority"),
        ("workflow.update_state", "update_workflow", "P5_review_gated_experimental_planner", "E5_internally_replicated_evidence", "execution_payload_preparation"),
        ("robot_queue.submit", "submit_run", "P6_authorized_closed_loop_lab_agent", "E6_independently_reproduced_evidence", "robot_queue_submission"),
        ("publication.draft_claim", "draft_claim", "P5_review_gated_experimental_planner", "E5_internally_replicated_evidence", "publication_claim"),
    ],
)
def test_review_trigger_requested_scope_on_gate(
    gate: AKTAGate,
    tool: str,
    action: str,
    profile: str,
    evidence: str,
    expected_scope: str,
) -> None:
    decision = gate.evaluate(
        ai_output={"summary": f"Test {action}."},
        requested_tool=tool,
        requested_action=action,
        context=AKTAContext.from_dict({"evidence_state": evidence, "domain": "materials"}),
        deployment_profile=profile,
        domain_overlay="generic_lab_v0" if tool in ("lab_scheduler.prioritize", "workflow.update_state") else None,
    )
    d = decision.to_dict()
    assert d["admissibility"] in ("review_required", "authorization_required"), d["admissibility"]
    trigger = d.get("review_trigger")
    assert trigger is not None
    assert trigger["requested_scope"] == expected_scope
    assert trigger["review_trigger_version"] == "0.3"
    assert trigger["akta_decision_id"] == d["decision_id"]
