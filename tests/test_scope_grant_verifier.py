"""Grant verifier wiring and fail-closed mode tests (PR-2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta import AKTAContext, AKTAGate
from akta.capability_envelope import (
    ENVELOPE_VERSION,
    envelope_narrows,
    legacy_scope_to_envelope,
)
from akta.errors import GrantVerificationError
from akta.scope_grant_verifier import verify_scope_grant, verify_scope_grant_or_raise

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_unit_mode_warns_when_allowed_tools_absent() -> None:
    grant = {
        "grant_id": "SCOPE-GRANT-1",
        "authorization": {"approved_scope": "protocol_draft"},
    }
    result = verify_scope_grant(grant, mode="unit")
    assert result.ok
    assert any("allowed_tools" in w for w in result.warnings)
    assert result.capability_envelope is not None
    assert result.capability_envelope["legacy_approved_scope"] == "protocol_draft"


def test_release_mode_rejects_missing_allowed_tools() -> None:
    grant = {
        "grant_id": "SCOPE-GRANT-2",
        "authorization": {"approved_scope": "protocol_draft"},
    }
    with pytest.raises(GrantVerificationError, match="allowed_tools"):
        verify_scope_grant_or_raise(grant, mode="release")


def test_production_env_rejects_simulated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    grant = {
        "grant_id": "SCOPE-GRANT-SIM",
        "authorization": {"approved_scope": "protocol_draft", "allowed_tools": []},
        "adapter_mode": "simulated",
    }
    with pytest.raises(GrantVerificationError, match="simulated"):
        verify_scope_grant_or_raise(grant)


def test_evaluate_with_grant_fail_closed_missing_tools(gate: AKTAGate) -> None:
    grant = {
        "grant_id": "SCOPE-GRANT-MISS",
        "authorization": {"approved_scope": "protocol_draft"},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    with pytest.raises(GrantVerificationError, match="allowed_tools"):
        gate.evaluate_with_grant(
            ai_output={"summary": "Draft"},
            requested_tool="protocol_editor.draft_change",
            requested_action="draft",
            context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
            deployment_profile="P4_protocol_drafting_assistant",
            scope_grant=grant,
            verification_mode="pilot",
        )


def test_evaluate_with_grant_attaches_envelope(gate: AKTAGate) -> None:
    grant = {
        "grant_id": "SCOPE-GRANT-ENV",
        "authorization": {
            "approved_scope": "protocol_draft",
            "allowed_tools": ["protocol_editor.draft_change"],
        },
        "expires_at": "2030-01-01T00:00:00Z",
    }
    decision = gate.evaluate_with_grant(
        ai_output={"summary": "Draft timing tweak."},
        requested_tool="protocol_editor.draft_change",
        requested_action="draft_timing",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P4_protocol_drafting_assistant",
        scope_grant=grant,
        verification_mode="unit",
    )
    data = decision.to_dict()
    assert data.get("capability_envelope", {}).get("envelope_version") == ENVELOPE_VERSION
    assert data.get("grant_layer_satisfaction", {}).get("evidence_never_satisfied_by_grant") is True
    assert data.get("review_satisfied") is True or data.get("admissibility") == "blocked"


def test_capability_envelope_narrowing() -> None:
    wide = legacy_scope_to_envelope(
        approved_scope="protocol_draft",
        allowed_tools=["protocol_editor.draft_change", "protocol_editor.update_active_protocol"],
    )
    narrow = legacy_scope_to_envelope(
        approved_scope="protocol_draft",
        allowed_tools=["protocol_editor.draft_change"],
    )
    assert envelope_narrows(wide, narrow)
    assert not envelope_narrows(narrow, wide)


def test_cross_family_envelopes_incomparable() -> None:
    protocol = legacy_scope_to_envelope(
        approved_scope="protocol_draft",
        allowed_tools=["protocol_editor.draft_change"],
    )
    publication = legacy_scope_to_envelope(
        approved_scope="publication_claim",
        allowed_tools=["protocol_editor.draft_change"],
    )
    assert not envelope_narrows(protocol, publication)
    assert not envelope_narrows(publication, protocol)


def test_envelope_narrows_responsibility_and_environment() -> None:
    granted = legacy_scope_to_envelope(
        approved_scope="protocol_draft",
        allowed_tools=["protocol_editor.draft_change"],
        max_responsibility_level="R4",
    )
    granted["environment"] = "lab-a"
    requested = dict(granted)
    requested["max_responsibility_level"] = "R6"
    assert not envelope_narrows(granted, requested)
    requested = dict(granted)
    requested["max_responsibility_level"] = "R3"
    requested["environment"] = "lab-b"
    assert not envelope_narrows(granted, requested)
    requested = dict(granted)
    requested["max_responsibility_level"] = "R3"
    requested["environment"] = "lab-a"
    assert envelope_narrows(granted, requested)


def test_require_envelope_rejects_scalar_only() -> None:
    grant = {
        "grant_id": "SCOPE-GRANT-SCALAR",
        "authorization": {"approved_scope": "protocol_draft", "allowed_tools": ["x"]},
    }
    with pytest.raises(GrantVerificationError, match="capability_envelope"):
        verify_scope_grant_or_raise(grant, mode="unit", require_capability_envelope=True)


def test_explicit_envelope_accepted() -> None:
    grant = {
        "grant_id": "SCOPE-GRANT-CE",
        "capability_envelope": {
            "envelope_version": ENVELOPE_VERSION,
            "capability_family": "protocol",
            "operation": "draft",
            "allowed_tools": ["protocol_editor.draft_change"],
            "max_responsibility_level": "R4",
        },
        "authorization": {"approved_scope": "protocol_draft"},
    }
    result = verify_scope_grant_or_raise(grant, mode="release", require_capability_envelope=True)
    assert result.ok
    assert result.capability_envelope["capability_family"] == "protocol"
