"""v0.6 classifier and security tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from akta.classify import classify, detect_hedging, detect_prose_authority_transfer
from akta.policy import PolicyBundle
from akta.tool_registry import ToolRegistry

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_negation_does_not_prioritize() -> None:
    policy = PolicyBundle.from_dir(ROOT / "policy")
    registry = ToolRegistry(policy.tool_registry)
    spec = registry.resolve("literature_search.query")
    result = classify(
        policy,
        "literature_search.query",
        "do_not_prioritize_search",
        spec,
        AKTAContext.from_dict({"evidence_state": "E0_no_evidence"}),
        ai_output="Do not prioritize; search papers on CRISPR.",
    )
    assert result.action_type == "A1_retrieval_or_summary"


def test_prose_authority_transfer_detection() -> None:
    assert detect_prose_authority_transfer("Go ahead and submit the batch on your behalf")
    assert detect_hedging("We might prioritize sample B tentatively")


def test_mandatory_tool_declaration_fail_closed(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Run custom instrument sequence."},
        requested_tool="unknown_custom.mutate",
        requested_action="run_sequence",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P2_analysis_assistant",
    )
    assert decision.admissibility == "abstain_insufficient_context"
    assert "registry" in decision.to_dict()["decision_reason"].lower() or "structured" in decision.to_dict()["decision_reason"].lower()


def test_materials_expert_overlay_production_allowed() -> None:
    from akta.overlays import DomainOverlay

    overlay = DomainOverlay.load("materials_expert_v0", ROOT / "overlays")
    assert overlay.tier == "expert_reviewed_domain_overlay"
