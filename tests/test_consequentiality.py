"""Tests for consequentiality-aware admissibility (v0.2)."""

from __future__ import annotations

from pathlib import Path

from akta import AKTAGate, AKTAContext

ROOT = Path(__file__).resolve().parent.parent


def test_non_consequential_a3_allowed_with_logging() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Interpret FTIR peak at 1700 cm-1."},
        requested_tool="notebook.run_analysis",
        requested_action="interpret_spectrum",
        context=AKTAContext.from_dict({
            "evidence_state": "E4_internally_consistent_evidence",
            "validation_status": "V2_simulation_supported",
        }),
        deployment_profile="P3_review_gated_evidence_interpreter",
        domain_overlay="computational_science_v0",
    )
    d = decision.to_dict()
    assert d["admissibility"] == "allowed_with_logging"
    assert d["consequentiality"] is False


def test_consequential_a3_next_run_review_required() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Analysis suggests we should run condition B next."},
        requested_tool="notebook.run_analysis",
        requested_action="interpret_and_recommend_next_run",
        context=AKTAContext.from_dict({
            "evidence_state": "E4_internally_consistent_evidence",
        }),
        deployment_profile="P3_review_gated_evidence_interpreter",
    )
    d = decision.to_dict()
    assert d["admissibility"] == "review_required"
    assert d["consequentiality"] is True
    assert "next-run" in d["consequentiality_reason"] or "recommend" in d["consequentiality_reason"].lower()


def test_consequential_a3_publication_review_required() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Interpret data for manuscript claim section."},
        requested_tool="notebook.run_analysis",
        requested_action="interpret_for_manuscript",
        context=AKTAContext.from_dict({"evidence_state": "E3_noisy_or_conflicting_evidence"}),
        deployment_profile="P3_review_gated_evidence_interpreter",
    )
    d = decision.to_dict()
    assert d["admissibility"] == "review_required"
    assert d["consequentiality"] is True


def test_handoff_escalation_marks_consequentiality() -> None:
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
    assert d["consequentiality"] is True
    assert "handoff" in d["consequentiality_reason"].lower()
