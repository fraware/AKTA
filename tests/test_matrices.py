"""Tests for admissibility and evidence-to-action matrix enforcement."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_p2_blocks_queue_prioritization_by_profile(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize run B."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_next_run",
        context=AKTAContext.from_dict({
            "evidence_state": "E7_deployment_validated_evidence",
            "validation_status": "V6_operationally_validated",
        }),
        deployment_profile="P2_analysis_assistant",
        domain_overlay="generic_lab_v0",
    )
    assert decision.admissibility == "blocked"


def test_e2_blocks_prioritization_even_under_p5(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize run B."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_next_run",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P5_review_gated_experimental_planner",
        domain_overlay="generic_lab_v0",
    )
    d = decision.to_dict()
    assert d["admissibility"] in ("blocked", "review_required")
    assert d["evidence_state"] == "E2_preliminary_signal"


def test_blocked_decisions_include_next_steps(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Submit robot payload."},
        requested_tool="robot_queue.submit",
        requested_action="submit_run",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P5_review_gated_experimental_planner",
    )
    d = decision.to_dict()
    assert d["admissibility"] in ("blocked", "authorization_required")
    assert len(d["next_admissible_steps"]) > 0
