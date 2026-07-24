"""AKTA 1.2 P0-6 … P0-10: source chain, client, replay store, signed status."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from akta.hash import hash_object
from akta.scope_authorization_manifest import (
    REQUIRED_MANIFEST_HASH_FIELDS,
    clear_manifest_cache,
    compute_manifest_hash,
    unsigned_manifest_body,
    verify_authorization_manifest,
)
from akta.scope_client import (
    ScopeAuthorizationClient,
    ScopeClientConfig,
    ScopeClientError,
)
from akta.scope_grant_verifier import (
    _artifact_id_and_hash,
    verify_scope_grant,
)
from akta.status_replay_store import StatusReplayStore, status_hash_for_replay
from tests.helpers.institutional_grant import (
    make_institutional_kit,
    make_signed_grant,
    make_source_artifacts,
    sign_status,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_manifest_cache()


@pytest.fixture
def kit(tmp_path: Path) -> dict:
    return make_institutional_kit(tmp_path)


def _start_json_server(payload: dict[str, Any]) -> tuple[HTTPServer, str]:
    body = json.dumps(payload).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


def test_artifact_hash_missing_not_synthesized() -> None:
    art_id, art_hash, errors = _artifact_id_and_hash(
        {"record_id": "rec-1", "summary": "body-without-hash"}
    )
    assert art_id == "rec-1"
    assert art_hash is None
    assert any("refusing silent local hash synthesis" in e for e in errors)


def test_signed_artifact_ref_required_for_remote() -> None:
    incomplete = {
        "artifact_id": "rec-1",
        "artifact_hash": "sha256:" + ("a" * 64),
        "store_id": "store-1",
    }
    _id, _hash, errors = _artifact_id_and_hash(incomplete)
    assert _id is None
    assert any("signed artifact reference missing" in e for e in errors)

    complete = {
        "artifact_id": "rec-1",
        "artifact_hash": "sha256:" + ("a" * 64),
        "store_id": "store-1",
        "tenant_id": "tenant-a",
        "attestation": "sig-bytes",
    }
    art_id, art_hash, errors = _artifact_id_and_hash(complete)
    assert not errors
    assert art_id == "rec-1"
    assert art_hash == complete["artifact_hash"]


def test_strict_requires_full_source_chain(kit: dict) -> None:
    grant, status, arts = make_signed_grant(kit)
    grant["source"].pop("scope_decision_id", None)
    grant["source"].pop("scope_decision_hash", None)
    from akta.shared_contracts import _contracts

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


def test_manifest_requires_canonical_registry_hashes(kit: dict) -> None:
    for field_name in (
        "delegation_policy_hash",
        "status_attestor_registry_hash",
        "manifest_signer_registry_hash",
        "runtime_evaluator_registry_hash",
    ):
        assert field_name in REQUIRED_MANIFEST_HASH_FIELDS

    result = verify_authorization_manifest(
        kit["manifest"],
        expected_hash=kit["trust_root"],
        trust_store=kit["manifest_store"],
        require_crypto=True,
    )
    assert result.ok, result.errors


def test_manifest_never_transformed_after_signing(kit: dict) -> None:
    body = unsigned_manifest_body(kit["manifest"])
    recomputed = compute_manifest_hash({"manifest_hash": "ignored", **body})
    assert recomputed == kit["manifest"]["manifest_hash"]
    # Mutating after the fact must not be how verification works — hash excludes sigs.
    tampered = dict(kit["manifest"])
    tampered["scope_policy_hash"] = "sha256:" + ("9" * 64)
    bad = verify_authorization_manifest(
        tampered,
        expected_hash=kit["trust_root"],
        trust_store=kit["manifest_store"],
        require_crypto=True,
    )
    assert not bad.ok


def test_scope_client_rejects_unsigned_and_cross_origin(
    kit: dict, tmp_path: Path
) -> None:
    grant, status, _arts = make_signed_grant(kit)
    server, base = _start_json_server(status)
    try:
        client = ScopeAuthorizationClient(
            ScopeClientConfig(
                status_url=base + "/{grant_id}",
                timeout_seconds=2.0,
                require_transport_auth=False,
            )
        )
        got = client.get_status(grant["grant_id"])
        assert got["grant_id"] == grant["grant_id"]
        assert got.get("attestation_signature")
    finally:
        server.shutdown()

    unsigned_server, unsigned_base = _start_json_server(
        {"grant_id": grant["grant_id"], "status": "active"}
    )
    try:
        client = ScopeAuthorizationClient(
            ScopeClientConfig(
                status_url=unsigned_base + "/{grant_id}",
                require_transport_auth=False,
            )
        )
        with pytest.raises(ScopeClientError, match="attestation signature"):
            client.get_status(grant["grant_id"])
    finally:
        unsigned_server.shutdown()

    with pytest.raises(ScopeClientError, match="OIDC|mTLS"):
        ScopeAuthorizationClient(
            ScopeClientConfig(
                status_url="https://example.invalid/status/{grant_id}",
                require_transport_auth=True,
            )
        ).get_status("g1")


def test_status_replay_store_acceptance_rules(tmp_path: Path) -> None:
    store = StatusReplayStore(tmp_path / "replay", max_checked_at_age_seconds=3600)
    checked = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    first = store.evaluate(
        tenant_id="tenant-a",
        grant_id="g1",
        status_attestor_key_id="attestor-1",
        ledger_sequence=1,
        status_hash="sha256:" + ("a" * 64),
        checked_at=checked,
    )
    assert first.accepted and not first.idempotent

    idem = store.evaluate(
        tenant_id="tenant-a",
        grant_id="g1",
        status_attestor_key_id="attestor-1",
        ledger_sequence=1,
        status_hash="sha256:" + ("a" * 64),
        checked_at=checked,
    )
    assert idem.accepted and idem.idempotent

    conflict = store.evaluate(
        tenant_id="tenant-a",
        grant_id="g1",
        status_attestor_key_id="attestor-1",
        ledger_sequence=1,
        status_hash="sha256:" + ("b" * 64),
        checked_at=checked,
    )
    assert not conflict.accepted
    assert any("hash conflict" in e for e in conflict.errors)

    older = store.evaluate(
        tenant_id="tenant-a",
        grant_id="g1",
        status_attestor_key_id="attestor-1",
        ledger_sequence=0,
        status_hash="sha256:" + ("a" * 64),
        checked_at=checked,
    )
    assert not older.accepted

    newer = store.evaluate(
        tenant_id="tenant-a",
        grant_id="g1",
        status_attestor_key_id="attestor-1",
        ledger_sequence=2,
        status_hash="sha256:" + ("c" * 64),
        checked_at=checked,
    )
    assert newer.accepted and not newer.idempotent

    rotated = store.evaluate(
        tenant_id="tenant-a",
        grant_id="g1",
        status_attestor_key_id="attestor-2",
        ledger_sequence=3,
        status_hash="sha256:" + ("d" * 64),
        checked_at=checked,
        previously_seen_attestors={"attestor-1"},
    )
    assert not rotated.accepted
    assert any("authorized rotation" in e for e in rotated.errors)


def test_verifier_uses_replay_store_not_grant_dict(kit: dict, tmp_path: Path) -> None:
    grant, status, arts = make_signed_grant(kit)
    store = StatusReplayStore(tmp_path / "replay", max_checked_at_age_seconds=3600)
    status["checked_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status = sign_status(status, kit["status_keys"])

    ok = verify_scope_grant(
        grant,
        mode="release",
        trust_store=kit["issuer_store"],
        ledger_status=status,
        authorization_manifest=kit["manifest"],
        source_artifacts=arts,
        status_trust_store=kit["status_store"],
        manifest_trust_store=kit["manifest_store"],
        replay_store=store,
    )
    assert ok.ok, ok.errors
    assert "_last_seen_ledger_sequence" not in grant

    # Same sequence different hash → reject via durable store.
    conflict = dict(status)
    conflict["cardinality_remaining"] = 1
    conflict["ledger_sequence"] = status["ledger_sequence"]
    conflict["uses_consumed"] = 99
    conflict.pop("attestation_hash", None)
    conflict.pop("attestation_signature", None)
    conflict.pop("signed_payload_hash", None)
    conflict = sign_status(conflict, kit["status_keys"])
    assert conflict["attestation_hash"] != status["attestation_hash"]
    bad = verify_scope_grant(
        grant,
        mode="release",
        trust_store=kit["issuer_store"],
        ledger_status=conflict,
        authorization_manifest=kit["manifest"],
        source_artifacts=arts,
        status_trust_store=kit["status_store"],
        manifest_trust_store=kit["manifest_store"],
        replay_store=store,
    )
    assert not bad.ok
    assert any("hash conflict" in e or "replay" in e for e in bad.errors)


def test_strict_rejects_unsigned_embedded_ledger(kit: dict) -> None:
    grant, _status, arts = make_signed_grant(kit)
    unsigned = {
        "grant_id": grant["grant_id"],
        "status": "active",
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cardinality_remaining": 1,
        "grant_hash": grant["grant_hash"],
        "scope_trust_root_hash": kit["trust_root"],
        "tenant_id": "tenant-a",
        "ledger_sequence": 1,
    }
    grant["ledger_status"] = unsigned
    result = verify_scope_grant(
        grant,
        mode="release",
        trust_store=kit["issuer_store"],
        ledger_status=None,
        authorization_manifest=kit["manifest"],
        source_artifacts=arts,
        status_trust_store=kit["status_store"],
        manifest_trust_store=kit["manifest_store"],
    )
    assert not result.ok
    assert any("unsigned embedded" in e or "signed status" in e for e in result.errors)


def test_strict_rejects_exhausted_and_missing_cardinality(kit: dict) -> None:
    grant, status, arts = make_signed_grant(kit)
    exhausted = dict(status)
    exhausted["status"] = "exhausted"
    exhausted["cardinality_remaining"] = 0
    exhausted["checked_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    exhausted = sign_status(exhausted, kit["status_keys"])
    bad = verify_scope_grant(
        grant,
        mode="release",
        trust_store=kit["issuer_store"],
        ledger_status=exhausted,
        authorization_manifest=kit["manifest"],
        source_artifacts=arts,
        status_trust_store=kit["status_store"],
        manifest_trust_store=kit["manifest_store"],
    )
    assert not bad.ok
    assert any("exhausted" in e or "remaining" in e for e in bad.errors)

    missing = dict(status)
    missing.pop("cardinality_remaining", None)
    missing.pop("single_use_remaining", None)
    missing["checked_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    missing = sign_status(missing, kit["status_keys"])
    bad2 = verify_scope_grant(
        grant,
        mode="release",
        trust_store=kit["issuer_store"],
        ledger_status=missing,
        authorization_manifest=kit["manifest"],
        source_artifacts=arts,
        status_trust_store=kit["status_store"],
        manifest_trust_store=kit["manifest_store"],
    )
    assert not bad2.ok
    assert any("cardinality" in e for e in bad2.errors)


def test_authenticated_ledger_verifier_accepted(kit: dict) -> None:
    grant, status, arts = make_signed_grant(kit)
    status["checked_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status = sign_status(status, kit["status_keys"])

    class _Verifier:
        def get_status(self, grant_id: str) -> dict[str, Any]:
            assert grant_id == grant["grant_id"]
            return status

    result = verify_scope_grant(
        grant,
        mode="release",
        trust_store=kit["issuer_store"],
        ledger_status=None,
        authorization_manifest=kit["manifest"],
        source_artifacts=arts,
        status_trust_store=kit["status_store"],
        manifest_trust_store=kit["manifest_store"],
        ledger_verifier=_Verifier(),
    )
    assert result.ok, result.errors


def test_source_artifacts_include_scope_decision() -> None:
    arts = make_source_artifacts()
    assert "scope_decision" in arts
    assert arts["scope_decision"]["scope_decision_hash"].startswith("sha256:")
    assert status_hash_for_replay({"attestation_hash": "sha256:abc"}) == "sha256:abc"
