"""Tests for AKTAGate."""

from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_weak_evidence_blocked_under_p2(gate: AKTAGate) -> None:
    ctx = AKTAContext.from_dict({
        "domain": "materials",
        "evidence_state": "E2_preliminary_signal",
        "validation_status": "V0_unvalidated",
    })
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize condition B based on preliminary signal."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_next_run",
        context=ctx,
        deployment_profile="P2_analysis_assistant",
        domain_overlay="generic_lab_v0",
    )
    d = decision.to_dict()
    assert d["admissibility"] == "blocked"
    assert d["scientific_action_type"] == "A7_resource_or_queue_prioritization"
    assert d["responsibility_level"] == "R6_resource_allocation"
    assert d["evidence_state"] == "E2_preliminary_signal"
    assert d["policy_hash"].startswith("sha256:")
    assert d["tool_registry_hash"].startswith("sha256:")
    assert len(d["next_admissible_steps"]) > 0


def test_unknown_mutating_tool_abstains(gate: AKTAGate) -> None:
    ctx = AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"})
    decision = gate.evaluate(
        ai_output="Do something unknown",
        requested_tool="unknown.mutating_tool",
        requested_action="mutate_state",
        context=ctx,
        deployment_profile="P5_review_gated_experimental_planner",
    )
    assert decision.admissibility == "abstain_insufficient_context"


def test_review_required_emits_trigger(gate: AKTAGate) -> None:
    ctx = AKTAContext.from_dict({
        "evidence_state": "E5_internally_replicated_evidence",
        "validation_status": "V4_internally_replicated",
    })
    decision = gate.evaluate(
        ai_output={"summary": "Recommend next experiment based on replicated evidence."},
        requested_tool="experiment_planner.create_run_plan",
        requested_action="create_run_plan",
        context=ctx,
        deployment_profile="P3_review_gated_evidence_interpreter",
        domain_overlay="computational_science_v0",
    )
    d = decision.to_dict()
    if d["admissibility"] == "review_required":
        assert d.get("review_trigger") is not None


def test_p7_not_supported() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy")
    with pytest.raises(Exception):
        gate.evaluate(
            ai_output="test",
            requested_tool="literature_search.query",
            requested_action="search",
            context=AKTAContext(),
            deployment_profile="P7_fully_autonomous_scientific_operator",
        )
