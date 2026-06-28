"""Tests for review context enforcement (F12/F14)."""

from __future__ import annotations

from pathlib import Path

from akta import AKTAGate, AKTAContext

ROOT = Path(__file__).resolve().parent.parent


def test_f14_stale_review_blocks_scope_exceeded() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize queue"},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_after_review",
        context=AKTAContext.from_dict({
            "evidence_state": "E4_internally_consistent_evidence",
            "metadata": {
                "prior_review_id": "REV-OLD-001",
                "prior_review_scope": "draft_only",
                "prior_review_expired": True,
            },
        }),
        deployment_profile="P5_review_gated_experimental_planner",
        domain_overlay="generic_lab_v0",
    )
    assert decision.admissibility == "blocked"


def test_f14_expired_draft_requires_new_review() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Activate plan"},
        requested_tool="experiment_planner.create_run_plan",
        requested_action="activate_plan",
        context=AKTAContext.from_dict({
            "evidence_state": "E4_internally_consistent_evidence",
            "metadata": {
                "prior_review_id": "REV-DRAFT-OLD",
                "prior_review_scope": "draft_only",
                "prior_review_expired": True,
            },
        }),
        deployment_profile="P5_review_gated_experimental_planner",
    )
    assert decision.admissibility == "review_required"


def test_f12_disclaimer_without_boundary_escalates() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Update active protocol threshold"},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_threshold",
        context=AKTAContext.from_dict({
            "evidence_state": "E5_internally_replicated_evidence",
            "metadata": {"disclaimer": "AI output may be incorrect."},
        }),
        deployment_profile="P4_protocol_drafting_assistant",
    )
    assert decision.admissibility == "review_required"


def test_prior_akta_records_block_escalation() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    prior = [{
        "classification": {"scientific_action_type": "A4_recommendation"},
        "decision": {"admissibility": "blocked"},
    }]
    decision = gate.evaluate(
        ai_output={"summary": "Submit to robot queue"},
        requested_tool="robot_queue.submit",
        requested_action="submit",
        context=AKTAContext.from_dict({
            "evidence_state": "E5_internally_replicated_evidence",
            "prior_akta_records": prior,
        }),
        deployment_profile="P6_authorized_closed_loop_lab_agent",
    )
    assert decision.admissibility == "blocked"
