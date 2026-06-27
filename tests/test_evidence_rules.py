"""Tests for per-action evidence-to-action rules (v0.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_e2_a4_under_p3_review_or_draft(gate: AKTAGate) -> None:
    from akta.consequentiality import classify_consequentiality
    from akta.evaluate import evaluate_admissibility
    from akta.tool_registry import ToolRegistry

    registry = ToolRegistry(gate.policy.tool_registry)
    tool_spec = registry.resolve("experiment_planner.create_run_plan")
    ctx = AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"})
    cons = classify_consequentiality(
        "A4_recommendation", tool_spec, "experiment_planner.create_run_plan",
        "recommend_next_step", {"summary": "Recommend next step."}, ctx,
    )
    result = evaluate_admissibility(
        gate.policy, "P3_review_gated_evidence_interpreter", "A4_recommendation",
        "E2_preliminary_signal", tool_spec, "experiment_planner.create_run_plan",
        ctx, consequentiality=cons,
    )
    assert result.admissibility in ("draft_only", "review_required")


def test_e2_a5_active_protocol_review_or_blocked(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Update active protocol threshold."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_threshold",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
    )
    assert decision.admissibility in ("review_required", "blocked")


def test_e2_a6_validation_draft_only(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Draft validation experiment."},
        requested_tool="experiment_planner.create_validation_draft",
        requested_action="draft_validation_experiment",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P3_review_gated_evidence_interpreter",
    )
    assert decision.admissibility == "draft_only"


def test_e2_a7_blocked(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize batch B."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_batch_b",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P5_review_gated_experimental_planner",
        domain_overlay="generic_lab_v0",
    )
    assert decision.admissibility == "blocked"


def test_e2_a9_blocked(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Submit to robot queue."},
        requested_tool="robot_queue.submit",
        requested_action="submit_run",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P6_authorized_closed_loop_lab_agent",
    )
    assert decision.admissibility == "blocked"


def test_e5_a6_under_p5_review_required(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Create run plan with replicated evidence."},
        requested_tool="experiment_planner.create_run_plan",
        requested_action="create_run_plan",
        context=AKTAContext.from_dict({
            "evidence_state": "E5_internally_replicated_evidence",
            "validation_status": "V4_internally_replicated",
        }),
        deployment_profile="P5_review_gated_experimental_planner",
    )
    assert decision.admissibility == "review_required"


def test_e6_a7_under_p6_authorization_required(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize independently reproduced batch."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_batch",
        context=AKTAContext.from_dict({
            "evidence_state": "E6_independently_reproduced_evidence",
            "validation_status": "V5_independently_replicated",
        }),
        deployment_profile="P6_authorized_closed_loop_lab_agent",
        domain_overlay="generic_lab_v0",
    )
    assert decision.admissibility == "authorization_required"


def test_e2_no_rank_loophole_for_a5_draft_tool(gate: AKTAGate) -> None:
    """E2 must not permit arbitrary A5 via legacy rank loophole."""
    decision = gate.evaluate(
        ai_output={"summary": "Update active protocol now."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_active",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P3_review_gated_evidence_interpreter",
    )
    assert decision.admissibility != "allowed"
    assert decision.admissibility != "allowed_with_logging"


def test_e2_a5_active_vs_draft_protocol_tools(gate: AKTAGate) -> None:
    """E2 + A5: active protocol mutation is stricter than draft-only pathway."""
    active = gate.evaluate(
        ai_output={"summary": "Change active incubation timing."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="change_timing",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P4_protocol_drafting_assistant",
    )
    draft = gate.evaluate(
        ai_output={"summary": "Draft protocol tweak for review."},
        requested_tool="protocol_editor.draft_change",
        requested_action="draft_tweak",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P4_protocol_drafting_assistant",
    )
    assert active.admissibility in ("blocked", "review_required")
    assert draft.admissibility == "draft_only"
