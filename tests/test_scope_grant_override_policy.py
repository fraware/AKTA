"""Tests for SCOPE grant layer satisfaction (v1.0 RC — evidence override removed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from akta.grant_override import (
    LEGACY_EVIDENCE_OVERRIDE_KEY,
    compute_grant_layer_satisfaction,
    grant_may_satisfy_evidence,
)
from akta.scope_grant_verifier import verify_scope_grant

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_grant_may_never_satisfy_evidence_layer() -> None:
    assert grant_may_satisfy_evidence(
        deployment_profile="P2_analysis_assistant",
        evidence_state="E2_preliminary_signal",
    ) is False
    assert grant_may_satisfy_evidence(
        deployment_profile="P5_review_gated_experimental_planner",
        evidence_state="E4_internally_consistent_evidence",
    ) is False


def test_layer_satisfaction_marks_review_not_evidence() -> None:
    grant = {
        "grant_id": "SCOPE-GRANT-TEST",
        "authorization": {"approved_scope": "protocol_draft"},
    }
    result = compute_grant_layer_satisfaction(grant)
    layers = {entry["layer"] for entry in result["satisfied_layers"]}
    assert layers == {"human_review", "authorization"}
    assert "evidence" not in layers
    assert result["evidence_never_satisfied_by_grant"] is True


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
        "grant_id": "SCOPE-GRANT-CASE-C",
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
    satisfaction = regate.to_dict().get("grant_layer_satisfaction") or {}
    assert satisfaction.get("evidence_never_satisfied_by_grant") is True
    unsatisfied = {entry["layer"] for entry in satisfaction.get("unsatisfied_layers") or []}
    assert "evidence" in unsatisfied


def test_p5_e4_grant_does_not_skip_evidence_layer(gate: AKTAGate) -> None:
    """P5+E4 grant must not waive evidence_rules; layered satisfaction only."""
    from akta.classify import classify
    from akta.consequentiality import classify_consequentiality
    from akta.evaluate import evaluate_admissibility
    from akta.review_loop import prepare_grant_context

    grant = {
        "grant_id": "SCOPE-GRANT-P5",
        "authorization": {"approved_scope": "robot_queue_submission"},
        "source": {"requested_scope": "robot_queue_submission"},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    prepared = prepare_grant_context(
        {"evidence_state": "E4_internally_consistent_evidence"},
        scope_grant=grant,
        trigger={"requested_scope": "robot_queue_submission"},
        deployment_profile="P5_review_gated_experimental_planner",
    )
    metadata = prepared.context["metadata"]
    assert LEGACY_EVIDENCE_OVERRIDE_KEY not in metadata
    assert metadata["grant_layer_satisfaction"]["evidence_never_satisfied_by_grant"] is True

    # Even if a caller injects the legacy flag, evaluate must still apply evidence.
    poisoned = dict(prepared.context)
    poisoned_meta = dict(poisoned.get("metadata") or {})
    poisoned_meta[LEGACY_EVIDENCE_OVERRIDE_KEY] = True
    poisoned["metadata"] = poisoned_meta

    ctx = AKTAContext.from_dict(poisoned)
    tool = "robot_queue.submit"
    tool_spec = gate.tool_registry.resolve(tool)
    classification = classify(
        gate.policy, tool, "submit_run", tool_spec, ctx, ai_output={"summary": "x"}
    )
    cons = classify_consequentiality(
        classification.action_type, tool_spec, tool, "submit_run", {"summary": "x"}, ctx, None
    )
    result = evaluate_admissibility(
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
    # Evidence rules remain in the composition path whenever they fire.
    # (May or may not produce a blocking layer depending on matrix; presence of
    # the legacy flag must not suppress appending when evidence_decision returns.)
    from akta.evaluate import evidence_decision

    ev_dec, _ = evidence_decision(
        gate.policy,
        "E4_internally_consistent_evidence",
        classification.action_type,
        "P5_review_gated_experimental_planner",
        tool_spec,
        tool,
        cons,
    )
    if ev_dec:
        assert any(layer.source == "evidence_rules" for layer in result.layers)


def test_empty_allowed_tools_denies_all(gate: AKTAGate) -> None:
    grant = {
        "grant_id": "SCOPE-GRANT-EMPTY",
        "authorization": {
            "approved_scope": "protocol_draft",
            "allowed_tools": [],
        },
        "source": {"requested_scope": "protocol_draft"},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    regate = gate.evaluate_with_grant(
        ai_output={"summary": "Draft protocol note."},
        requested_tool="protocol_editor.draft_change",
        requested_action="draft",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P4_protocol_drafting_assistant",
        scope_grant=grant,
        trigger={"requested_scope": "protocol_draft"},
    )
    assert regate.admissibility == "blocked"


def test_verifier_rejects_simulated_in_release_mode() -> None:
    grant = {
        "grant_id": "SCOPE-GRANT-SIM",
        "authorization": {"approved_scope": "protocol_draft", "allowed_tools": []},
        "adapter_mode": "simulated",
    }
    unit = verify_scope_grant(grant, mode="unit")
    assert unit.ok
    release = verify_scope_grant(grant, mode="release")
    assert not release.ok
    assert any("simulated" in err for err in release.errors)
