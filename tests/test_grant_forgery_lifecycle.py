"""P0-C forgery and lifecycle failure acceptance tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta.capability_envelope import legacy_scope_to_envelope
from akta.errors import GrantVerificationError
from akta.scope_grant_verifier import verify_scope_grant, verify_scope_grant_or_raise
from akta.shared_contracts import (
    ENVELOPE_VERSION,
    _contracts,
    authorization_envelope_schema_hash,
)
from akta.trust_store import (
    build_trust_store,
    generate_test_keypair,
    sign_payload_hash_ed25519,
)


def _envelope(**overrides: object) -> dict:
    base = legacy_scope_to_envelope(
        approved_scope="protocol_draft",
        allowed_tools=["protocol_editor.draft_change"],
        blocked_tools=["robot_queue.submit"],
    )
    base.update(overrides)
    return base


def _unsigned_base_grant(**overrides: object) -> dict:
    envelope = _envelope()
    grant = {
        "grant_id": "SCOPE-GRANT-FORGE-1",
        "grant_version": "2.0.0",
        "created_at": "2026-01-01T00:00:00Z",
        "authorization": {
            "approved_scope": "protocol_draft",
            "allowed_tools": envelope["allowed_tools"],
            "blocked_tools": envelope["blocked_tools"],
            "authorization_envelope": envelope,
        },
        "authorization_schema_version": ENVELOPE_VERSION,
        "authorization_schema_hash": authorization_envelope_schema_hash(),
        "issuer": {"issuer_identity": "scope-test", "issuer_key_id": "pending"},
        "source": {
            "packet_id": "pkt-1",
            "decision_id": "dec-1",
            "akta_record_id": "rec-1",
        },
        "provenance": {"scope_trust_root_hash": "sha256:" + ("d" * 64)},
        "constraints": {"single_use": True, "policy_manifest_hash": "sha256:" + ("e" * 64)},
        "expiration": {
            "absolute_expiration": "2030-01-01T00:00:00Z",
            "expires_after": ["protocol_version_change", "model_version_change"],
        },
    }
    grant.update(overrides)
    return grant


@pytest.fixture
def issuer_keys(tmp_path: Path) -> dict[str, str]:
    return generate_test_keypair(tmp_path / "keys")


@pytest.fixture
def trust_store(issuer_keys: dict[str, str], tmp_path: Path) -> dict:
    registry = {
        "keys": {
            issuer_keys["public_key_ref"]: {
                "public_key_pem": issuer_keys["public_key_pem"],
                "public_key_ref": issuer_keys["public_key_ref"],
                "status": "active",
            }
        },
        "revoked_key_ids": [],
        "source": str(tmp_path),
    }
    return build_trust_store(registry, base_dir=tmp_path)


def _sign_grant(grant: dict, issuer_keys: dict[str, str]) -> dict:
    grant = dict(grant)
    grant["issuer"] = {
        "issuer_identity": "scope-test",
        "issuer_key_id": issuer_keys["public_key_ref"],
    }
    grant = _contracts().attach_hash(grant, "grant_hash")
    grant["signed_payload_hash"] = grant["grant_hash"]
    priv = Path(issuer_keys["private_key_path"]).read_bytes()
    grant["grant_signature"] = sign_payload_hash_ed25519(priv, grant["grant_hash"])
    grant["signature_algorithm"] = "Ed25519"
    return grant


def test_unsigned_grant_fails_in_pilot() -> None:
    grant = _unsigned_base_grant()
    grant = _contracts().attach_hash(grant, "grant_hash")
    with pytest.raises(GrantVerificationError, match="unsigned grant"):
        verify_scope_grant_or_raise(grant, mode="pilot")


def test_invalid_grant_hash_fails(issuer_keys: dict[str, str], trust_store: dict) -> None:
    grant = _sign_grant(_unsigned_base_grant(), issuer_keys)
    grant["grant_hash"] = "sha256:" + ("0" * 64)
    with pytest.raises(GrantVerificationError, match="grant_hash"):
        verify_scope_grant_or_raise(grant, mode="pilot", trust_store=trust_store)


def test_unknown_issuer_fails(issuer_keys: dict[str, str], trust_store: dict) -> None:
    grant = _sign_grant(_unsigned_base_grant(), issuer_keys)
    grant["issuer"]["issuer_key_id"] = "sha256:" + ("f" * 64)
    with pytest.raises(GrantVerificationError, match="unknown issuer"):
        verify_scope_grant_or_raise(grant, mode="pilot", trust_store=trust_store)


def test_revoked_issuer_key_fails(issuer_keys: dict[str, str], tmp_path: Path) -> None:
    registry = {
        "keys": {
            issuer_keys["public_key_ref"]: {
                "public_key_pem": issuer_keys["public_key_pem"],
                "public_key_ref": issuer_keys["public_key_ref"],
                "status": "revoked",
            }
        },
        "revoked_key_ids": [issuer_keys["public_key_ref"]],
        "source": str(tmp_path),
    }
    store = build_trust_store(registry, base_dir=tmp_path)
    grant = _sign_grant(_unsigned_base_grant(), issuer_keys)
    with pytest.raises(GrantVerificationError, match="revoked issuer"):
        verify_scope_grant_or_raise(grant, mode="pilot", trust_store=store)


def test_wrong_akta_record_fails(issuer_keys: dict[str, str], trust_store: dict) -> None:
    grant = _sign_grant(_unsigned_base_grant(), issuer_keys)
    with pytest.raises(GrantVerificationError, match="wrong AKTA record"):
        verify_scope_grant_or_raise(
            grant,
            mode="pilot",
            trust_store=trust_store,
            record={"record_id": "rec-OTHER"},
        )


def test_wrong_packet_fails(issuer_keys: dict[str, str], trust_store: dict) -> None:
    grant = _sign_grant(_unsigned_base_grant(), issuer_keys)
    with pytest.raises(GrantVerificationError, match="wrong packet"):
        verify_scope_grant_or_raise(
            grant,
            mode="pilot",
            trust_store=trust_store,
            expected_packet_id="pkt-OTHER",
        )


def test_stale_policy_manifest_fails(issuer_keys: dict[str, str], trust_store: dict) -> None:
    grant = _sign_grant(_unsigned_base_grant(), issuer_keys)
    with pytest.raises(GrantVerificationError, match="stale policy manifest"):
        verify_scope_grant_or_raise(
            grant,
            mode="pilot",
            trust_store=trust_store,
            context={"metadata": {"policy_manifest_hash": "sha256:" + ("a" * 64)}},
        )


def test_consumed_single_use_fails(issuer_keys: dict[str, str], trust_store: dict) -> None:
    grant = _sign_grant(_unsigned_base_grant(), issuer_keys)
    with pytest.raises(GrantVerificationError, match="single-use|consumed"):
        verify_scope_grant_or_raise(
            grant,
            mode="pilot",
            trust_store=trust_store,
            ledger_status={
                "grant_id": grant["grant_id"],
                "status": "active",
                "checked_at": "2026-01-02T00:00:00Z",
                "cardinality_remaining": 0,
                "single_use_remaining": 0,
                "grant_hash": grant["grant_hash"],
            },
        )


def test_revoked_grant_fails(issuer_keys: dict[str, str], trust_store: dict) -> None:
    grant = _sign_grant(_unsigned_base_grant(), issuer_keys)
    with pytest.raises(GrantVerificationError, match="revoked"):
        verify_scope_grant_or_raise(
            grant,
            mode="pilot",
            trust_store=trust_store,
            ledger_status={
                "grant_id": grant["grant_id"],
                "status": "revoked",
                "checked_at": "2026-01-02T00:00:00Z",
                "cardinality_remaining": 0,
                "revoked": True,
                "grant_hash": grant["grant_hash"],
            },
        )


def test_bound_context_protocol_and_model_required(
    issuer_keys: dict[str, str], trust_store: dict
) -> None:
    grant = _sign_grant(_unsigned_base_grant(), issuer_keys)
    with pytest.raises(GrantVerificationError, match="missing consequential grant context"):
        verify_scope_grant_or_raise(
            grant,
            mode="pilot",
            trust_store=trust_store,
            context={"metadata": {}},
        )


def test_fabricated_allowed_tools_fails(issuer_keys: dict[str, str], trust_store: dict) -> None:
    grant = _sign_grant(_unsigned_base_grant(), issuer_keys)
    grant["authorization"]["allowed_tools"] = ["totally.fabricated.tool"]
    grant = _contracts().attach_hash(grant, "grant_hash")
    grant["signed_payload_hash"] = grant["grant_hash"]
    priv = Path(issuer_keys["private_key_path"]).read_bytes()
    grant["grant_signature"] = sign_payload_hash_ed25519(priv, grant["grant_hash"])
    with pytest.raises(GrantVerificationError, match="fabricated allowed_tools"):
        verify_scope_grant_or_raise(grant, mode="pilot", trust_store=trust_store)


def test_valid_signed_grant_with_attestation(
    issuer_keys: dict[str, str], trust_store: dict
) -> None:
    grant = _sign_grant(
        _unsigned_base_grant(
            constraints={
                "single_use": True,
                "policy_manifest_hash": "sha256:" + ("e" * 64),
                "protocol_version": "proto-1",
            }
        ),
        issuer_keys,
    )
    attestation = {
        "grant_id": grant["grant_id"],
        "status": "active",
        "checked_at": "2026-01-02T00:00:00Z",
        "cardinality_remaining": 1,
        "single_use_remaining": 1,
        "grant_hash": grant["grant_hash"],
        "scope_trust_root_hash": grant["provenance"]["scope_trust_root_hash"],
        "attestation_key_id": issuer_keys["public_key_ref"],
        "issuer": {
            "issuer_identity": "scope-test",
            "issuer_key_id": issuer_keys["public_key_ref"],
        },
    }
    attestation = _contracts().attach_hash(attestation, "attestation_hash")
    attestation["signed_payload_hash"] = attestation["attestation_hash"]
    priv = Path(issuer_keys["private_key_path"]).read_bytes()
    attestation["attestation_signature"] = sign_payload_hash_ed25519(
        priv, attestation["attestation_hash"]
    )
    result = verify_scope_grant_or_raise(
        grant,
        mode="pilot",
        trust_store=trust_store,
        ledger_status=attestation,
        context={
            "metadata": {
                "policy_manifest_hash": "sha256:" + ("e" * 64),
                "protocol_version": "proto-1",
                "bound_protocol_version": "proto-1",
            }
        },
        record={"record_id": "rec-1"},
    )
    assert result.ok, result.errors


def test_production_requires_trust_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKTA_PRODUCTION_MODE", "1")
    monkeypatch.delenv("AKTA_TRUST_STORE_PATH", raising=False)
    monkeypatch.delenv("AKTA_ISSUER_KEY_REGISTRY", raising=False)
    grant = _contracts().attach_hash(_unsigned_base_grant(), "grant_hash")
    result = verify_scope_grant(grant, mode="production")
    assert not result.ok
    assert any("trust store" in e for e in result.errors)
