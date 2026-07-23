"""AKTA 1.1 WS4–7: grant schema gate, manifest, status, source hashes."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta.errors import GrantVerificationError
from akta.scope_authorization_manifest import (
    clear_manifest_cache,
    verify_authorization_manifest,
)
from akta.scope_grant_verifier import (
    migrate_legacy_grant_to_v2,
    verify_scope_grant,
    verify_scope_grant_or_raise,
)
from akta.shared_contracts import _contracts
from tests.helpers.institutional_grant import (
    make_institutional_kit,
    make_signed_grant,
    make_source_artifacts,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_manifest_cache()


@pytest.fixture
def kit(tmp_path: Path) -> dict:
    return make_institutional_kit(tmp_path)


def test_release_rejects_legacy_grant_version(kit: dict) -> None:
    grant, status, arts = make_signed_grant(kit)
    grant["grant_version"] = "akta-scope-grant-v1.0"
    grant = _contracts().attach_hash(grant, "grant_hash")
    grant["signed_payload_hash"] = grant["grant_hash"]
    result = verify_scope_grant(
        grant,
        mode="release",
        trust_store=kit["issuer_store"],
        ledger_status=status,
        authorization_manifest=kit["manifest"],
        source_artifacts=arts,
        status_trust_store=kit["status_store"],
        manifest_trust_store=kit["manifest_store"],
    )
    assert not result.ok
    assert any("legacy grant version" in e for e in result.errors)


def test_release_rejects_missing_signature_algorithm(kit: dict) -> None:
    grant, status, arts = make_signed_grant(kit)
    grant.pop("signature_algorithm", None)
    result = verify_scope_grant(
        grant,
        mode="release",
        trust_store=kit["issuer_store"],
        ledger_status=status,
        authorization_manifest=kit["manifest"],
        source_artifacts=arts,
        status_trust_store=kit["status_store"],
        manifest_trust_store=kit["manifest_store"],
    )
    assert not result.ok
    assert any("signature_algorithm missing" in e for e in result.errors)


def test_release_rejects_missing_source_hashes(kit: dict) -> None:
    grant, status, arts = make_signed_grant(kit)
    grant["source"] = {
        "packet_id": "pkt-1",
        "decision_id": "dec-1",
        "akta_record_id": "rec-1",
    }
    grant = _contracts().attach_hash(grant, "grant_hash")
    grant["signed_payload_hash"] = grant["grant_hash"]
    result = verify_scope_grant(
        grant,
        mode="release",
        trust_store=kit["issuer_store"],
        ledger_status=status,
        authorization_manifest=kit["manifest"],
        source_artifacts=arts,
        status_trust_store=kit["status_store"],
        manifest_trust_store=kit["manifest_store"],
    )
    assert not result.ok
    assert any("missing source hashes" in e for e in result.errors)


def test_release_rejects_unknown_grant_version(kit: dict) -> None:
    grant, status, arts = make_signed_grant(kit)
    grant["grant_version"] = "9.9.9-unknown"
    result = verify_scope_grant(
        grant,
        mode="release",
        trust_store=kit["issuer_store"],
        ledger_status=status,
        authorization_manifest=kit["manifest"],
        source_artifacts=arts,
        status_trust_store=kit["status_store"],
        manifest_trust_store=kit["manifest_store"],
    )
    assert not result.ok
    assert any("unknown grant schema version" in e for e in result.errors)


def test_migrate_legacy_grant_cli_helper() -> None:
    legacy = {
        "grant_id": "LEGACY-1",
        "authorization": {
            "approved_scope": "protocol_draft",
            "allowed_tools": ["protocol_editor.draft_change"],
        },
    }
    migrated = migrate_legacy_grant_to_v2(legacy)
    assert migrated["grant_version"] == "2.0.0"
    assert "authorization_envelope" in migrated["authorization"]


def test_authorization_manifest_binds_trust_root(kit: dict) -> None:
    result = verify_authorization_manifest(
        kit["manifest"],
        expected_hash=kit["trust_root"],
        trust_store=kit["manifest_store"],
        require_crypto=True,
    )
    assert result.ok
    assert result.manifest_hash == kit["trust_root"]


def test_strict_rejects_trust_root_without_manifest(kit: dict) -> None:
    grant, status, arts = make_signed_grant(kit)
    result = verify_scope_grant(
        grant,
        mode="pilot",
        trust_store=kit["issuer_store"],
        ledger_status=status,
        source_artifacts=arts,
        status_trust_store=kit["status_store"],
        manifest_trust_store=kit["manifest_store"],
        # no authorization_manifest and no pin/fetch
    )
    assert not result.ok
    assert any("authorization manifest" in e for e in result.errors)


def test_grant_status_unavailable_in_strict(kit: dict) -> None:
    grant, _status, arts = make_signed_grant(kit)
    result = verify_scope_grant(
        grant,
        mode="release",
        trust_store=kit["issuer_store"],
        authorization_manifest=kit["manifest"],
        source_artifacts=arts,
        status_trust_store=kit["status_store"],
        manifest_trust_store=kit["manifest_store"],
        ledger_status=None,
    )
    assert not result.ok
    assert any(e == "grant_status_unavailable" for e in result.errors)


def test_grant_status_rejects_stale_and_wrong_hash(kit: dict) -> None:
    grant, status, arts = make_signed_grant(kit)
    status["checked_at"] = "2020-01-01T00:00:00Z"
    status["grant_hash"] = "sha256:" + ("0" * 64)
    from tests.helpers.institutional_grant import sign_status

    status = sign_status(status, kit["status_keys"])
    result = verify_scope_grant(
        grant,
        mode="release",
        trust_store=kit["issuer_store"],
        ledger_status=status,
        authorization_manifest=kit["manifest"],
        source_artifacts=arts,
        status_trust_store=kit["status_store"],
        manifest_trust_store=kit["manifest_store"],
    )
    assert not result.ok
    assert any("stale" in e or "grant_hash" in e for e in result.errors)


def test_source_hash_mismatch_different_record(kit: dict) -> None:
    grant, status, arts = make_signed_grant(kit)
    other = dict(arts["record"])
    other["record_id"] = "rec-other"
    other["summary"] = "different"
    from akta.hash import hash_object

    other["record_hash"] = hash_object(
        {k: v for k, v in other.items() if k != "record_hash"}
    )
    bad_arts = dict(arts)
    bad_arts["record"] = other
    # Keep grant bound to rec-1 hash but supply different record artifact.
    result = verify_scope_grant(
        grant,
        mode="release",
        trust_store=kit["issuer_store"],
        ledger_status=status,
        authorization_manifest=kit["manifest"],
        source_artifacts=bad_arts,
        status_trust_store=kit["status_store"],
        manifest_trust_store=kit["manifest_store"],
        record=other,
    )
    assert not result.ok
    assert any("hash" in e or "record" in e for e in result.errors)


def test_strict_accepts_full_institutional_grant(kit: dict) -> None:
    grant, status, arts = make_signed_grant(kit)
    result = verify_scope_grant_or_raise(
        grant,
        mode="release",
        trust_store=kit["issuer_store"],
        ledger_status=status,
        authorization_manifest=kit["manifest"],
        source_artifacts=arts,
        status_trust_store=kit["status_store"],
        manifest_trust_store=kit["manifest_store"],
    )
    assert result.ok
    assert result.authorization_manifest_hash == kit["trust_root"]
