"""Structured action schema enforcement tests (directive §7)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from akta import AKTAContext, AKTAGate
from akta.structured_action_policy import (
    default_structured_action_for_tool,
    load_structured_action_schema,
    require_structured_actions_for_known_tools,
)

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def _decl(tool: str, action: str = "act", *, external_effect: bool = False, **extra: object) -> dict:
    d = default_structured_action_for_tool(tool, action, external_effect=external_effect)
    d.update(extra)
    return d


def test_unknown_mutating_requires_structured_action(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Run mystery mutator."},
        requested_tool="unknown_vendor.mystery_mutator",
        requested_action="mutate",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P2_analysis_assistant",
    )
    assert decision.admissibility == "abstain_insufficient_context"


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


def test_known_mutating_requires_declaration_by_default(
    gate: AKTAGate, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AKTA_REQUIRE_STRUCTURED_ACTIONS", raising=False)
    schema = load_structured_action_schema(str(ROOT / "policy"))
    assert schema is not None
    assert require_structured_actions_for_known_tools(schema) is True
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize weak batch."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P2_analysis_assistant",
    )
    assert decision.admissibility == "abstain_insufficient_context"


def test_known_mutating_passes_schema_then_policy_may_block(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize weak batch."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize",
        context=AKTAContext.from_dict({
            "evidence_state": "E2_preliminary_signal",
            "structured_action": _decl(
                "lab_scheduler.prioritize",
                "prioritize",
                external_effect=True,
            ),
        }),
        deployment_profile="P2_analysis_assistant",
    )
    assert decision.admissibility == "blocked"


def test_rejects_unknown_action_type(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Mutate."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize",
        context=AKTAContext.from_dict({
            "evidence_state": "E2_preliminary_signal",
            "structured_action": _decl(
                "lab_scheduler.prioritize",
                "prioritize",
                external_effect=True,
                action_type="A99_not_real",
            ),
        }),
        deployment_profile="P2_analysis_assistant",
    )
    assert decision.admissibility == "abstain_insufficient_context"
    assert "unknown action type" in decision.to_dict()["decision_reason"]


def test_rejects_family_mismatch(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize",
        context=AKTAContext.from_dict({
            "evidence_state": "E2_preliminary_signal",
            "structured_action": _decl(
                "lab_scheduler.prioritize",
                "prioritize",
                external_effect=True,
                capability_family="publication",
            ),
        }),
        deployment_profile="P2_analysis_assistant",
    )
    assert decision.admissibility == "abstain_insufficient_context"
    assert "family mismatch" in decision.to_dict()["decision_reason"]


def test_env_can_disable_known_requirement(
    gate: AKTAGate, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AKTA_REQUIRE_STRUCTURED_ACTIONS", "0")
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize weak batch."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P2_analysis_assistant",
    )
    assert decision.admissibility == "blocked"
