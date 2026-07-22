"""Grant layer-satisfaction policy tests (v1.0 RC)."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from akta.grant_override import grant_may_satisfy_evidence

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_p2_grant_does_not_satisfy_evidence() -> None:
    assert grant_may_satisfy_evidence(
        deployment_profile="P2_analysis_assistant",
        evidence_state="E2_preliminary_signal",
    ) is False


def test_p5_grant_also_cannot_satisfy_evidence() -> None:
    assert grant_may_satisfy_evidence(
        deployment_profile="P5_review_gated_experimental_planner",
        evidence_state="E4_internally_consistent_evidence",
    ) is False


def test_case_c_p2_e2_stays_blocked_after_grant(gate: AKTAGate) -> None:
    """Case C: P2+E2 queue prioritize stays blocked even with SCOPE grant."""
    ctx = {
        "evidence_state": "E2_preliminary_signal",
        "validation_status": "V0_unvalidated",
        "structured_action": {
            "tool_name": "lab_scheduler.prioritize",
            "action_intent": "prioritize",
            "target_resource": "lab_scheduler",
            "external_effects_declared": True,
            "external_effects": ["external"],
        },
    }
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize weak signal batch."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize",
        context=AKTAContext.from_dict(ctx),
        deployment_profile="P2_analysis_assistant",
    )
    d = decision.to_dict()
    record = decision.to_record().to_dict()
    trigger = d.get("review_trigger") or {
        "requested_scope": "single_run_queue_priority",
        "blocked_tools": d.get("blocked_tools", []),
    }
    grant = {
        "grant_id": "SCOPE-GRANT-CASE-C",
        "authorization": {"approved_scope": "single_run_queue_priority"},
        "source": {"requested_scope": "single_run_queue_priority"},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    regate = gate.evaluate_with_grant(
        ai_output={"summary": "Prioritize after grant."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize",
        context=AKTAContext.from_dict(ctx),
        deployment_profile="P2_analysis_assistant",
        scope_grant=grant,
        record=record,
        trigger=trigger,
    )
    assert regate.admissibility == "blocked"


def test_positive_control_p5_e4_grant_allows_scoped_action(gate: AKTAGate) -> None:
    """Positive control: grant satisfies review/auth when evidence policy already permits."""
    decision = gate.evaluate(
        ai_output={"summary": "Create validation run plan."},
        requested_tool="experiment_planner.create_run_plan",
        requested_action="create_plan",
        context=AKTAContext.from_dict({
            "evidence_state": "E4_internally_consistent_evidence",
        }),
        deployment_profile="P5_review_gated_experimental_planner",
    )
    d = decision.to_dict()
    record = decision.to_record().to_dict()
    trigger = d.get("review_trigger") or {
        "requested_scope": "single_validation_plan",
        "blocked_tools": [],
    }
    grant = {
        "grant_id": "SCOPE-GRANT-POS",
        "authorization": {
            "approved_scope": "single_validation_plan",
            "allowed_tools": ["experiment_planner.create_run_plan"],
        },
        "source": {"requested_scope": "single_validation_plan"},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    regate = gate.evaluate_with_grant(
        ai_output={"summary": "Create plan after grant."},
        requested_tool="experiment_planner.create_run_plan",
        requested_action="create_plan",
        context=AKTAContext.from_dict({
            "evidence_state": "E4_internally_consistent_evidence",
        }),
        deployment_profile="P5_review_gated_experimental_planner",
        scope_grant=grant,
        record=record,
        trigger=trigger,
    )
    assert regate.admissibility in ("review_required", "allowed_with_logging", "draft_only", "allowed")
    satisfaction = regate.to_dict().get("grant_layer_satisfaction") or {}
    assert satisfaction.get("evidence_never_satisfied_by_grant") is True
    satisfied = {entry["layer"] for entry in satisfaction.get("satisfied_layers") or []}
    assert "human_review" in satisfied
    assert "evidence" not in satisfied
