"""Tests for strengthened classifier (v0.2)."""

from __future__ import annotations

from pathlib import Path

from akta import AKTAGate, AKTAContext
from akta.classify import classify
from akta.policy import PolicyBundle
from akta.tool_registry import ToolRegistry

ROOT = Path(__file__).resolve().parent.parent


def test_known_tool_overrides_nl() -> None:
    policy = PolicyBundle.from_dir(ROOT / "policy")
    registry = ToolRegistry(policy.tool_registry)
    tool_spec = registry.resolve("literature_search.query")
    result = classify(
        policy,
        "literature_search.query",
        "prioritize_next_run",
        tool_spec,
        AKTAContext(),
    )
    assert result.action_type == "A1_retrieval_or_summary"
    assert result.matched_source == "tool_registry"
    assert "nl_tool_mismatch" in result.uncertainty_flags


def test_ambiguous_wording_flags() -> None:
    policy = PolicyBundle.from_dir(ROOT / "policy")
    registry = ToolRegistry(policy.tool_registry)
    tool_spec = registry.resolve("notebook.run_analysis")
    result = classify(
        policy,
        "notebook.run_analysis",
        "interpret_or_recommend_or_prioritize",
        tool_spec,
        AKTAContext(),
    )
    assert result.confidence <= 0.98


def test_handoff_escalation_classification() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Place D at top of queue."},
        requested_tool="literature_search.query",
        requested_action="summarize_and_schedule",
        context=AKTAContext.from_dict({
            "evidence_state": "E3_noisy_or_conflicting_evidence",
            "handoff_chain": [
                {"agent_id": "a1", "action_type": "A2_hypothesis_generation", "responsibility_level": "R1_epistemic_assistance"},
                {"agent_id": "a2", "action_type": "A6_experimental_planning", "responsibility_level": "R5_experimental_planning"},
                {"agent_id": "a3", "action_type": "A7_resource_or_queue_prioritization", "responsibility_level": "R6_resource_allocation"},
            ],
        }),
        deployment_profile="P5_review_gated_experimental_planner",
        domain_overlay="generic_lab_v0",
    )
    d = decision.to_dict()
    assert d["scientific_action_type"] == "A7_resource_or_queue_prioritization"
    assert "handoff_escalation" in d["classification"]["uncertainty_flags"]


def test_low_confidence_mutating_fail_closed() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output="unclear",
        requested_tool="unregistered.custom_mutator",
        requested_action="do_something",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P5_review_gated_experimental_planner",
    )
    assert decision.admissibility == "abstain_insufficient_context"


def test_classification_audit_fields_present() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Search literature."},
        requested_tool="literature_search.query",
        requested_action="search",
        context=AKTAContext(),
        deployment_profile="P1_literature_hypothesis_assistant",
    )
    d = decision.to_dict()
    cls = d["classification"]
    assert cls["classifier_mode"] == "deterministic"
    assert cls["matched_source"] == "tool_registry"
    assert "classification_rationale" in d
