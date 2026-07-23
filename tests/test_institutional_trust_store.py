"""Institutional trust store and grant-status attestation acceptance tests."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml

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
    institutional_registry_is_empty,
    load_issuer_registry,
    resolve_trust_store,
    sign_payload_hash_ed25519,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_KEYS = ROOT / "tests" / "fixtures" / "trust_keys"
FIXTURE_REGISTRY = FIXTURE_KEYS / "issuer_registry.yaml"
POLICY_REGISTRY = ROOT / "policy" / "scope_grant_issuer_registry.yaml"


def _envelope() -> dict[str, Any]:
    return legacy_scope_to_envelope(
        approved_scope="protocol_draft",
        allowed_tools=["protocol_editor.draft_change"],
        blocked_tools=["robot_queue.submit"],
    )


def _base_grant(*, key_id: str) -> dict[str, Any]:
    envelope = _envelope()
    return {
        "grant_id": "SCOPE-GRANT-TRUST-1",
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
        "issuer": {"issuer_identity": "akta-test-issuer", "issuer_key_id": key_id},
        "source": {
            "packet_id": "pkt-trust-1",
            "decision_id": "dec-trust-1",
            "akta_record_id": "rec-trust-1",
        },
        "provenance": {"scope_trust_root_hash": "sha256:" + ("a" * 64)},
        "constraints": {"single_use": True, "policy_manifest_hash": "sha256:" + ("b" * 64)},
        "expiration": {
            "absolute_expiration": "2030-01-01T00:00:00Z",
            "expires_after": ["protocol_version_change"],
        },
    }


def _sign_grant(grant: dict[str, Any], private_pem: bytes, key_id: str) -> dict[str, Any]:
    grant = dict(grant)
    grant["issuer"] = {"issuer_identity": "akta-test-issuer", "issuer_key_id": key_id}
    grant = _contracts().attach_hash(grant, "grant_hash")
    grant["signed_payload_hash"] = grant["grant_hash"]
    grant["grant_signature"] = sign_payload_hash_ed25519(private_pem, grant["grant_hash"])
    grant["signature_algorithm"] = "Ed25519"
    return grant


@pytest.fixture
def fixture_trust_store() -> dict[str, Any]:
    registry = load_issuer_registry(FIXTURE_REGISTRY)
    return build_trust_store(
        registry,
        base_dir=FIXTURE_KEYS,
        required_artifact_type="scope_grant",
    )


def test_policy_registry_ships_empty_for_fail_closed() -> None:
    raw = yaml.safe_load(POLICY_REGISTRY.read_text(encoding="utf-8")) or {}
    assert raw.get("issuers") == {}
    store = build_trust_store(load_issuer_registry(POLICY_REGISTRY), base_dir=POLICY_REGISTRY.parent)
    assert institutional_registry_is_empty(store)


def test_fixture_registry_schema_fields() -> None:
    raw = yaml.safe_load(FIXTURE_REGISTRY.read_text(encoding="utf-8")) or {}
    entry = raw["issuers"]["akta-test-issuer-ed25519"]
    for field in ("key_id", "status", "algorithm", "valid_from", "valid_until"):
        assert field in entry
    assert entry["algorithm"] == "Ed25519"
    assert entry["status"] == "active"


def test_production_fails_closed_on_empty_registry() -> None:
    empty = build_trust_store({"keys": {}, "revoked_key_ids": []})
    grant = _base_grant(key_id="missing")
    result = verify_scope_grant(grant, mode="production", trust_store=empty)
    assert not result.ok
    assert any("trust store" in e for e in result.errors)


def test_unit_accepts_fixture_signed_grant(fixture_trust_store: dict[str, Any]) -> None:
    priv = (FIXTURE_KEYS / "issuer_ed25519.pem").read_bytes()
    key_id = "akta-test-issuer-ed25519"
    grant = _sign_grant(_base_grant(key_id=key_id), priv, key_id)
    result = verify_scope_grant(grant, mode="unit", trust_store=fixture_trust_store)
    assert result.ok, result.errors


def test_resolve_trust_store_from_fixture_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKTA_TRUST_STORE_PATH", str(FIXTURE_REGISTRY))
    store = resolve_trust_store(require_keys=True)
    assert store is not None
    assert not institutional_registry_is_empty(store)


def test_expired_key_rejected(fixture_trust_store: dict[str, Any]) -> None:
    # Mutate in-memory entry validity window to the past.
    for entry in fixture_trust_store["keys"].values():
        entry["valid_until"] = "2020-01-01T00:00:00Z"
    priv = (FIXTURE_KEYS / "issuer_ed25519.pem").read_bytes()
    key_id = "akta-test-issuer-ed25519"
    grant = _sign_grant(_base_grant(key_id=key_id), priv, key_id)
    with pytest.raises(GrantVerificationError):
        verify_scope_grant_or_raise(grant, mode="pilot", trust_store=fixture_trust_store)


def _start_attestation_server(payload: dict[str, Any]) -> tuple[HTTPServer, str]:
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


def test_grant_status_attestation_accept_and_reject(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """High-fidelity mock of authenticated SCOPE /grant-status attestation."""
    from datetime import datetime, timezone

    from tests.helpers.institutional_grant import make_institutional_kit, make_signed_grant

    kit = make_institutional_kit(tmp_path)
    grant, attestation, arts = make_signed_grant(
        kit,
        overrides={
            "constraints": {
                "single_use": True,
                "policy_manifest_hash": "sha256:" + ("b" * 64),
                "protocol_version": "proto-1",
                "tenant_id": "tenant-a",
            }
        },
    )
    # Ensure attestation is fresh for max-age checks.
    attestation["checked_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    from tests.helpers.institutional_grant import sign_status

    attestation = sign_status(attestation, kit["status_keys"])

    bound_context = {
        "metadata": {
            "policy_manifest_hash": "sha256:" + ("b" * 64),
            "protocol_version": "proto-1",
            "bound_protocol_version": "proto-1",
            "evidence_state": "E2_preliminary_signal",
            "validation_status": "none",
            "domain_overlay_hash": "sha256:" + ("c" * 64),
            "model_version": "test-model",
            "tool_registry_hash": "sha256:" + ("d" * 64),
            "grant_use_count": 0,
            "safety_incident_state": "none",
        }
    }

    server, base_url = _start_attestation_server(attestation)
    try:
        monkeypatch.setenv("SCOPE_GRANT_STATUS_URL", base_url + "/{grant_id}")
        ok_remote = verify_scope_grant(
            grant,
            mode="pilot",
            trust_store=kit["issuer_store"],
            ledger_status=None,
            authorization_manifest=kit["manifest"],
            source_artifacts=arts,
            status_trust_store=kit["status_store"],
            manifest_trust_store=kit["manifest_store"],
            context=bound_context,
            record=arts["record"],
        )
        assert ok_remote.ok, ok_remote.errors

        ok2 = verify_scope_grant(
            grant,
            mode="pilot",
            trust_store=kit["issuer_store"],
            ledger_status=attestation,
            authorization_manifest=kit["manifest"],
            source_artifacts=arts,
            status_trust_store=kit["status_store"],
            manifest_trust_store=kit["manifest_store"],
            context=bound_context,
            record=arts["record"],
        )
        assert ok2.ok, ok2.errors

        forged = dict(attestation)
        forged["attestation_signature"] = "AAAA"
        bad = verify_scope_grant(
            grant,
            mode="pilot",
            trust_store=kit["issuer_store"],
            ledger_status=forged,
            authorization_manifest=kit["manifest"],
            source_artifacts=arts,
            status_trust_store=kit["status_store"],
            manifest_trust_store=kit["manifest_store"],
            context=bound_context,
            record=arts["record"],
        )
        assert not bad.ok
        assert any("attestation" in e or "signature" in e for e in bad.errors)

        revoked = dict(attestation)
        revoked["status"] = "revoked"
        from tests.helpers.institutional_grant import sign_status

        revoked = sign_status(revoked, kit["status_keys"])
        bad2 = verify_scope_grant(
            grant,
            mode="pilot",
            trust_store=kit["issuer_store"],
            ledger_status=revoked,
            authorization_manifest=kit["manifest"],
            source_artifacts=arts,
            status_trust_store=kit["status_store"],
            manifest_trust_store=kit["manifest_store"],
            context=bound_context,
            record=arts["record"],
        )
        assert not bad2.ok
        assert any("revoked" in e or "status" in e for e in bad2.errors)
    finally:
        server.shutdown()
