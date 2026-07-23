"""Grant verifier wiring and shared envelope tests (P0-A/B/C)."""

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
from akta.shared_contracts import (
    authorization_envelope_schema_hash,
    shared_contract_report,
)

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def _shared_envelope(**overrides: object) -> dict:
    base = legacy_scope_to_envelope(
        approved_scope="protocol_draft",
        allowed_tools=["protocol_editor.draft_change"],
        blocked_tools=["robot_queue.submit"],
    )
    base.update(overrides)
    return base


def test_shared_contract_identity() -> None:
    report = shared_contract_report()
    assert report["envelope_schema_version"] == ENVELOPE_VERSION
    assert report["envelope_schema_hash"].startswith("sha256:")
    assert "interpretation" in report["family_vocabulary"]
    assert "queue" in report["family_vocabulary"]
    assert "memory" in report["family_vocabulary"]
    assert "queue_allocation" not in report["family_vocabulary"]


def test_unit_mode_warns_when_allowed_tools_absent() -> None:
    grant = {
        "grant_id": "SCOPE-GRANT-1",
        "authorization": {"approved_scope": "protocol_draft"},
    }
    result = verify_scope_grant(grant, mode="unit")
    assert result.ok
    assert any("allowed_tools" in w for w in result.warnings)
    assert result.capability_envelope is not None
    assert result.capability_envelope["family"] == "protocol"


def test_release_mode_rejects_missing_allowed_tools() -> None:
    grant = {
        "grant_id": "SCOPE-GRANT-2",
        "authorization": {"approved_scope": "protocol_draft"},
    }
    with pytest.raises(
        GrantVerificationError,
        match="authorization_envelope|allowed_tools|trust store",
    ):
        verify_scope_grant_or_raise(grant, mode="release")


def test_release_mode_rejects_scalar_only_grant() -> None:
    grant = {
        "grant_id": "SCOPE-GRANT-SCALAR",
        "authorization": {
            "approved_scope": "protocol_draft",
            "allowed_tools": ["protocol_editor.draft_change"],
        },
    }
    with pytest.raises(
        GrantVerificationError,
        match="authorization_envelope|trust store",
    ):
        verify_scope_grant_or_raise(grant, mode="pilot")


def test_production_env_rejects_simulated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from akta.trust_store import (
        build_trust_store,
        generate_test_keypair,
        sign_payload_hash_ed25519,
    )

    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    keys = generate_test_keypair(tmp_path / "keys")
    store = build_trust_store(
        {
            "keys": {
                keys["public_key_ref"]: {
                    "public_key_pem": keys["public_key_pem"],
                    "public_key_ref": keys["public_key_ref"],
                    "status": "active",
                    "algorithm": "Ed25519",
                    "authorized_artifact_types": ["scope_grant"],
                }
            },
            "revoked_key_ids": [],
            "default_artifact_types": ["scope_grant"],
        },
        base_dir=tmp_path,
        required_artifact_type="scope_grant",
    )
    envelope = _shared_envelope()
    grant = {
        "grant_id": "SCOPE-GRANT-SIM",
        "authorization": {
            "approved_scope": "protocol_draft",
            "allowed_tools": [],
            "authorization_envelope": envelope,
        },
        "adapter_mode": "simulated",
        "issuer": {
            "issuer_identity": "test",
            "issuer_key_id": keys["public_key_ref"],
        },
        "source": {
            "packet_id": "p1",
            "decision_id": "d1",
            "akta_record_id": "r1",
        },
        "provenance": {"scope_trust_root_hash": "sha256:" + ("b" * 64)},
        "constraints": {},
        "expiration": {"absolute_expiration": "2030-01-01T00:00:00Z", "expires_after": []},
        "authorization_schema_version": ENVELOPE_VERSION,
        "authorization_schema_hash": authorization_envelope_schema_hash(),
    }
    from akta.shared_contracts import _contracts

    grant = _contracts().attach_hash(grant, "grant_hash")
    grant["signed_payload_hash"] = grant["grant_hash"]
    priv = Path(keys["private_key_path"]).read_bytes()
    grant["grant_signature"] = sign_payload_hash_ed25519(priv, grant["grant_hash"])
    grant["signature_algorithm"] = "Ed25519"
    with pytest.raises(GrantVerificationError, match="simulated"):
        verify_scope_grant_or_raise(grant, trust_store=store)



def test_evaluate_with_grant_fail_closed_missing_tools(gate: AKTAGate) -> None:
    grant = {
        "grant_id": "SCOPE-GRANT-MISS",
        "authorization": {"approved_scope": "protocol_draft"},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    with pytest.raises(
        GrantVerificationError,
        match="authorization_envelope|allowed_tools|trust store",
    ):
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
    assert data.get("capability_envelope", {}).get("family") == "protocol"
    assert data.get("grant_layer_satisfaction", {}).get("evidence_never_satisfied_by_grant") is True


def test_capability_envelope_narrowing() -> None:
    wide = legacy_scope_to_envelope(
        approved_scope="protocol_draft",
        allowed_tools=["protocol_editor.draft_change", "protocol_editor.update_active_protocol"],
        blocked_tools=[],
    )
    narrow = legacy_scope_to_envelope(
        approved_scope="protocol_draft",
        allowed_tools=["protocol_editor.draft_change"],
        blocked_tools=[],
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
        environment={"tenant_id": "lab-a"},
    )
    requested = dict(granted)
    requested["responsibility_ceiling"] = "R6_physical_execution"
    assert not envelope_narrows(granted, requested)
    requested = dict(granted)
    requested["responsibility_ceiling"] = "R3_recommendation"
    requested["environment"] = {"tenant_id": "lab-b"}
    assert not envelope_narrows(granted, requested)
    requested = dict(granted)
    requested["responsibility_ceiling"] = "R3_recommendation"
    requested["environment"] = {"tenant_id": "lab-a"}
    assert envelope_narrows(granted, requested)


def test_require_envelope_rejects_scalar_only() -> None:
    grant = {
        "grant_id": "SCOPE-GRANT-SCALAR",
        "authorization": {"approved_scope": "protocol_draft", "allowed_tools": ["x"]},
    }
    with pytest.raises(GrantVerificationError, match="authorization_envelope|capability_envelope"):
        verify_scope_grant_or_raise(grant, mode="unit", require_capability_envelope=True)


def test_explicit_envelope_accepted(tmp_path: Path) -> None:
    from tests.helpers.institutional_grant import make_institutional_kit, make_signed_grant

    kit = make_institutional_kit(tmp_path)
    grant, status, arts = make_signed_grant(kit)
    result = verify_scope_grant_or_raise(
        grant,
        mode="release",
        require_capability_envelope=True,
        trust_store=kit["issuer_store"],
        ledger_status=status,
        authorization_manifest=kit["manifest"],
        source_artifacts=arts,
        status_trust_store=kit["status_store"],
        manifest_trust_store=kit["manifest_store"],
    )
    assert result.ok, result.errors
    assert result.capability_envelope["family"] == "protocol"
    assert "family" in result.capability_envelope
    assert "capability_family" not in result.capability_envelope
    assert "responsibility_ceiling" in result.capability_envelope
