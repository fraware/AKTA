"""Tests for explicit SCOPE grant override policy (v1.0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from akta.grant_override import grant_may_satisfy_evidence

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_p2_grant_may_not_satisfy_evidence_layer() -> None:
    assert grant_may_satisfy_evidence(
        deployment_profile="P2_analysis_assistant",
        evidence_state="E2_preliminary_signal",
    ) is False


def test_p5_e4_grant_may_satisfy_evidence_layer() -> None:
    assert grant_may_satisfy_evidence(
        deployment_profile="P5_review_gated_experimental_planner",
        evidence_state="E4_internally_consistent_evidence",
    ) is True


def test_case_c_p2_e2_stays_blocked_after_grant(gate: AKTAGate) -> None:
    """Case C: weak evidence under P2 remains blocked after SCOPE grant."""
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize condition B based on preliminary signal."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_next_run",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P2_analysis_assistant",
        domain_overlay="generic_lab_v0",
    )
    assert decision.admissibility in ("blocked", "review_required")

    grant = {
        "authorization": {"approved_scope": "single_run_queue_priority"},
        "source": {"requested_scope": "single_run_queue_priority"},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    trigger = {"requested_scope": "single_run_queue_priority"}
    regate = gate.evaluate_with_grant(
        ai_output={"summary": "Prioritize condition B based on preliminary signal."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_next_run",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P2_analysis_assistant",
        domain_overlay="generic_lab_v0",
        scope_grant=grant,
        trigger=trigger,
    )
    assert regate.admissibility == "blocked"


def test_p5_e4_grant_override_skips_evidence_layer(gate: AKTAGate) -> None:
    """P5+E4 grant sets metadata that waives the evidence_rules layer on re-gate."""
    from akta.classify import classify
    from akta.consequentiality import classify_consequentiality
    from akta.evaluate import evaluate_admissibility

    grant = {
        "authorization": {"approved_scope": "robot_queue_submission"},
        "source": {"requested_scope": "robot_queue_submission"},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    grant_state = gate.evaluate_with_grant(
        ai_output={"summary": "Submit run to robot queue."},
        requested_tool="robot_queue.submit",
        requested_action="submit_run",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P5_review_gated_experimental_planner",
        scope_grant=grant,
        trigger={"requested_scope": "robot_queue_submission"},
    )
    assert grant_state.to_dict().get("metadata") is None

    from akta.review_loop import prepare_grant_context

    prepared = prepare_grant_context(
        {"evidence_state": "E4_internally_consistent_evidence"},
        scope_grant=grant,
        trigger={"requested_scope": "robot_queue_submission"},
        deployment_profile="P5_review_gated_experimental_planner",
    )
    assert prepared.context["metadata"]["scope_grant_satisfies_evidence"] is True

    ctx = AKTAContext.from_dict(prepared.context)
    tool = "robot_queue.submit"
    tool_spec = gate.tool_registry.resolve(tool)
    classification = classify(
        gate.policy, tool, "submit_run", tool_spec, ctx, ai_output={"summary": "x"}
    )
    cons = classify_consequentiality(
        classification.action_type, tool_spec, tool, "submit_run", {"summary": "x"}, ctx, None
    )
    without_waiver = evaluate_admissibility(
        policy=gate.policy,
        profile="P5_review_gated_experimental_planner",
        action_type=classification.action_type,
        evidence_state="E4_internally_consistent_evidence",
        tool_spec=tool_spec,
        requested_tool=tool,
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        consequentiality=cons,
        requested_action="submit_run",
    )
    with_waiver = evaluate_admissibility(
        policy=gate.policy,
        profile="P5_review_gated_experimental_planner",
        action_type=classification.action_type,
        evidence_state="E4_internally_consistent_evidence",
        tool_spec=tool_spec,
        requested_tool=tool,
        context=ctx,
        consequentiality=cons,
        requested_action="submit_run",
    )
    assert any(layer.source == "evidence_rules" for layer in without_waiver.layers)
    assert not any(layer.source == "evidence_rules" for layer in with_waiver.layers)
