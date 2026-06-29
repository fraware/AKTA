"""Structured action schema enforcement tests (v1.0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_unknown_mutating_requires_structured_action(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Run mystery mutator."},
        requested_tool="unknown_vendor.mystery_mutator",
        requested_action="mutate",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P2_analysis_assistant",
    )
    assert decision.admissibility == "abstain_insufficient_context"
    reason = decision.to_dict().get("decision_reason", "")
    assert "structured_action" in reason.lower() or "declaration" in reason.lower()


def test_partial_structured_action_missing_fields(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Mutate."},
        requested_tool="unknown_lab.partial_mutator",
        requested_action="mutate",
        context=AKTAContext.from_dict({
            "evidence_state": "E4_internally_consistent_evidence",
            "structured_action": {"tool_name": "unknown_lab.partial_mutator"},
        }),
        deployment_profile="P2_analysis_assistant",
    )
    assert decision.admissibility == "abstain_insufficient_context"


def test_known_mutating_registry_does_not_require_structured_action(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize weak batch."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P2_analysis_assistant",
    )
    assert decision.admissibility == "blocked"
