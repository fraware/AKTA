"""Evidence-layer independence: grants never satisfy evidence (P0-F)."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta import AKTAContext, AKTAGate
from akta.capability_envelope import legacy_scope_to_envelope
from akta.errors import GrantVerificationError
from akta.shared_contracts import authorization_envelope_schema_hash

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def _grant_with_envelope(*, tools: list[str] | None = None) -> dict:
    tools = tools or ["protocol_editor.draft_change"]
    envelope = legacy_scope_to_envelope(
        approved_scope="protocol_draft",
        allowed_tools=tools,
        blocked_tools=["robot_queue.submit"],
    )
    return {
        "grant_id": "SCOPE-GRANT-EVIDENCE",
        "grant_version": "2.0.0",
        "authorization": {
            "approved_scope": "protocol_draft",
            "allowed_tools": tools,
            "blocked_tools": ["robot_queue.submit"],
            "authorization_envelope": envelope,
        },
        "authorization_schema_hash": authorization_envelope_schema_hash(),
        "constraints": {
            "evidence_state": "E4_internally_consistent_evidence",
            "protocol_version": "protocol_v1",
        },
        "expiration": {
            "absolute_expiration": "2030-01-01T00:00:00Z",
            "expires_after": ["evidence_state_change", "protocol_version_change"],
        },
        "issuer": {"issuer_identity": "scope-test", "issuer_key_id": "k1"},
        "grant_signature": "sig",
        "grant_hash": "sha256:" + ("e" * 64),
        "source": {
            "packet_id": "pkt-e",
            "decision_id": "dec-e",
            "akta_record_id": "rec-e",
        },
        "provenance": {"scope_trust_root_hash": "sha256:" + ("f" * 64)},
    }


def test_valid_grant_cannot_clear_weak_evidence_block(gate: AKTAGate) -> None:
    """Adversarial: valid SCOPE grant must not flip evidence blocks to allowed."""
    grant = _grant_with_envelope()
    decision = gate.evaluate_with_grant(
        ai_output={"summary": "Claim with weak evidence."},
        requested_tool="protocol_editor.draft_change",
        requested_action="draft",
        context=AKTAContext.from_dict(
            {
                "evidence_state": "E1_anecdotal_or_unverified",
                "protocol_version": "protocol_v1",
            }
        ),
        deployment_profile="P4_protocol_drafting_assistant",
        scope_grant=grant,
        verification_mode="unit",
    )
    data = decision.to_dict()
    satisfaction = data.get("grant_layer_satisfaction") or {}
    assert satisfaction.get("evidence_never_satisfied_by_grant") is True
    # Evidence layer must remain unsatisfied / not rewritten to allowed by grant alone
    # when policy would block/abstain on weak evidence for the action.
    if data.get("admissibility") in ("blocked", "abstain_insufficient_context"):
        for layer in satisfaction.get("satisfied_layers") or []:
            assert layer.get("layer") != "evidence"


def test_grant_records_layered_result(gate: AKTAGate) -> None:
    grant = _grant_with_envelope()
    decision = gate.evaluate_with_grant(
        ai_output={"summary": "Draft under grant."},
        requested_tool="protocol_editor.draft_change",
        requested_action="draft_timing",
        context=AKTAContext.from_dict(
            {
                "evidence_state": "E4_internally_consistent_evidence",
                "protocol_version": "protocol_v1",
            }
        ),
        deployment_profile="P4_protocol_drafting_assistant",
        scope_grant=grant,
        verification_mode="unit",
    )
    data = decision.to_dict()
    assert "grant_layer_satisfaction" in data or data.get("review_satisfied") is True
    satisfaction = data.get("grant_layer_satisfaction") or {}
    assert satisfaction.get("evidence_never_satisfied_by_grant") is True
