"""AS-03 decision basis tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.vsa.import_report import import_vsa_report
from akta.decision_basis import build_decision_basis
from akta.gate import AKTAGate
from akta.records import validate_against_schema

ROOT = Path(__file__).resolve().parents[1]


def test_basis_schema_and_policy_keys() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    basis = build_decision_basis(
        evaluation_layers=[
            {"source": "evidence_rules", "decision": "blocked", "reason": "weak evidence"},
            {"source": "deployment_profile", "decision": "allowed", "reason": "P2 allows analysis"},
        ],
        evidence_state="E2_preliminary_signal",
        admissibility="blocked",
        decision_reason="weak evidence",
        next_admissible_steps=[],
        required_review_role="domain_scientist",
        action_class="A1_literature_summary",
        policy=gate.policy,
    )
    validate_against_schema(basis, "decision_basis.schema.json")
    sources = {c["source"] for c in basis["applicable_policy_clauses"]}
    assert "evidence_rules" in sources or "policy_bundle" in sources
    assert any(c["clause_id"] == "evidence_rules" or c["source"] == "policy_bundle" for c in basis["applicable_policy_clauses"])
    assert basis["missing_evidence"]
    assert basis["next_admissible_steps"], "must not silently empty constructive steps"


def test_contradictory_evidence_lists_contradictions() -> None:
    basis = build_decision_basis(
        evaluation_layers=[
            {
                "source": "evidence_rules",
                "decision": "blocked",
                "reason": "conflicting evidence across claims",
            }
        ],
        evidence_state="E3_noisy_or_conflicting_evidence",
        admissibility="blocked",
        decision_reason="noisy/conflicting",
        next_admissible_steps=["gather_independent_replication"],
        required_review_role=None,
        action_class="A8_tool_or_workflow_mutation",
        context={"metadata": {"contradictions": ["claim_A_vs_claim_B"]}},
    )
    assert "conflicting_or_noisy_evidence_signal" in basis["contradictions"]
    assert "claim_A_vs_claim_B" in basis["contradictions"]


def test_insufficient_evidence_missing_populated() -> None:
    basis = build_decision_basis(
        evaluation_layers=[],
        evidence_state="E0_no_evidence",
        admissibility="abstain_insufficient_context",
        decision_reason="no evidence",
        next_admissible_steps=None,
        required_review_role=None,
        action_class="A1_literature_summary",
    )
    assert "sufficient_replicated_evidence" in basis["missing_evidence"]


def test_gate_attaches_decision_basis() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    report = {
        "report_id": "VSA-AS03",
        "overall_evidence_strength": "conflicting",
        "claims": [
            {"claim_id": "C1", "evidence_level": "conflicting"},
            {"claim_id": "C2", "evidence_level": "validated"},
        ],
    }
    decision = gate.evaluate(
        ai_output="mutate protocol",
        requested_tool="lab.protocol_update",
        requested_action="update",
        context=import_vsa_report(report),
    )
    data = decision.to_dict()
    assert "decision_basis" in data
    validate_against_schema(data["decision_basis"], "decision_basis.schema.json")
    assert data["bindings"].get("decision_basis_digest", "").startswith("sha256:")
