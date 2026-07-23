"""AKTA 1.1 WS2: crypto required in every strict grant mode."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta.capability_envelope import legacy_scope_to_envelope
from akta.errors import GrantVerificationError
from akta.scope_authorization_manifest import clear_manifest_cache
from akta.scope_grant_verifier import STRICT_MODES, verify_scope_grant, verify_scope_grant_or_raise
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
from tests.helpers.institutional_grant import make_institutional_kit, make_signed_grant


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_manifest_cache()


def _envelope() -> dict:
    return legacy_scope_to_envelope(
        approved_scope="protocol_draft",
        allowed_tools=["protocol_editor.draft_change"],
        blocked_tools=["robot_queue.submit"],
    )


def _base_grant(**overrides: object) -> dict:
    envelope = _envelope()
    grant = {
        "grant_id": "SCOPE-GRANT-STRICT-CRYPTO-1",
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
            "expires_after": [],
        },
    }
    grant.update(overrides)
    return grant


def _sign(grant: dict, issuer_keys: dict[str, str]) -> dict:
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
                "algorithm": "Ed25519",
                "authorized_artifact_types": ["scope_grant"],
            }
        },
        "revoked_key_ids": [],
        "source": str(tmp_path),
        "default_artifact_types": ["scope_grant"],
    }
    return build_trust_store(
        registry, base_dir=tmp_path, required_artifact_type="scope_grant"
    )


def test_pilot_rejects_structural_fake_signature() -> None:
    """Structural signature presence alone must never pass in pilot mode."""
    grant = _contracts().attach_hash(_base_grant(), "grant_hash")
    grant["signed_payload_hash"] = grant["grant_hash"]
    grant["grant_signature"] = "not-a-real-ed25519-signature"
    grant["signature_algorithm"] = "Ed25519"
    grant["issuer"] = {
        "issuer_identity": "fake",
        "issuer_key_id": "sha256:" + ("f" * 64),
    }
    result = verify_scope_grant(grant, mode="pilot")
    assert not result.ok
    assert any(
        "trust store" in e or "signature" in e or "unknown issuer" in e
        for e in result.errors
    )


def test_release_rejects_missing_trust_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AKTA_TRUST_STORE_PATH", raising=False)
    monkeypatch.delenv("AKTA_ISSUER_KEY_REGISTRY", raising=False)
    monkeypatch.delenv("AKTA_GRANT_ISSUER_REGISTRY", raising=False)
    grant = _contracts().attach_hash(_base_grant(), "grant_hash")
    grant["grant_signature"] = "structural-only"
    grant["signed_payload_hash"] = grant["grant_hash"]
    grant["issuer"] = {"issuer_identity": "x", "issuer_key_id": "k1"}
    result = verify_scope_grant(grant, mode="release")
    assert not result.ok
    assert any("trust store" in e for e in result.errors)


def test_cross_repo_rejects_unknown_issuer(
    issuer_keys: dict[str, str], trust_store: dict
) -> None:
    grant = _sign(_base_grant(), issuer_keys)
    grant["issuer"]["issuer_key_id"] = "sha256:" + ("a" * 64)
    grant = _contracts().attach_hash(grant, "grant_hash")
    grant["signed_payload_hash"] = grant["grant_hash"]
    with pytest.raises(GrantVerificationError, match="unknown issuer"):
        verify_scope_grant_or_raise(grant, mode="cross_repo", trust_store=trust_store)


def test_all_strict_modes_verify_final_grant_signature(tmp_path: Path) -> None:
    assert STRICT_MODES == frozenset({"pilot", "release", "cross_repo", "production"})
    kit = make_institutional_kit(tmp_path)
    good, status, arts = make_signed_grant(kit)
    for mode in sorted(STRICT_MODES):
        ok = verify_scope_grant(
            good,
            mode=mode,
            trust_store=kit["issuer_store"],
            ledger_status=status,
            authorization_manifest=kit["manifest"],
            source_artifacts=arts,
            status_trust_store=kit["status_store"],
            manifest_trust_store=kit["manifest_store"],
        )
        assert ok.ok, (mode, ok.errors)

        forged = dict(good)
        forged["grant_signature"] = "AAAA"
        bad = verify_scope_grant(
            forged,
            mode=mode,
            trust_store=kit["issuer_store"],
            ledger_status=status,
            authorization_manifest=kit["manifest"],
            source_artifacts=arts,
            status_trust_store=kit["status_store"],
            manifest_trust_store=kit["manifest_store"],
        )
        assert not bad.ok, mode
        assert any("signature" in e for e in bad.errors), (mode, bad.errors)
