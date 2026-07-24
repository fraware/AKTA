"""Shared builders for institutional grant / status / manifest fixtures."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from akta.capability_envelope import legacy_scope_to_envelope
from akta.hash import hash_object
from akta.scope_authorization_manifest import build_test_authorization_manifest
from akta.shared_contracts import ENVELOPE_VERSION, _contracts, authorization_envelope_schema_hash
from akta.trust_store import (
    build_trust_store,
    generate_test_keypair,
    sign_payload_hash_ed25519,
)


def make_source_artifacts() -> dict[str, Any]:
    record = {"record_id": "rec-1", "summary": "record-body"}
    decision = {"decision_id": "dec-1", "admissibility": "review_required"}
    packet = {"packet_id": "pkt-1", "payload": "packet"}
    trigger = {"review_trigger_id": "trg-1", "packet_id": "pkt-1"}
    scope_decision = {
        "scope_decision_id": "scope-dec-1",
        "outcome": "approved",
    }
    record["record_hash"] = hash_object(
        {k: v for k, v in record.items() if k != "record_hash"}
    )
    decision["decision_hash"] = hash_object(
        {k: v for k, v in decision.items() if k != "decision_hash"}
    )
    packet["packet_hash"] = hash_object(
        {k: v for k, v in packet.items() if k != "packet_hash"}
    )
    trigger["review_trigger_hash"] = hash_object(
        {k: v for k, v in trigger.items() if k != "review_trigger_hash"}
    )
    scope_decision["scope_decision_hash"] = hash_object(
        {k: v for k, v in scope_decision.items() if k != "scope_decision_hash"}
    )
    return {
        "record": record,
        "decision": decision,
        "packet": packet,
        "review_trigger": trigger,
        "scope_decision": scope_decision,
    }


def make_institutional_kit(tmp_path: Path) -> dict[str, Any]:
    """Issuer + status + manifest signer keys and trust stores."""
    issuer_keys = generate_test_keypair(tmp_path / "issuer")
    status_keys = generate_test_keypair(tmp_path / "status")
    manifest_keys = generate_test_keypair(tmp_path / "manifest")

    issuer_store = build_trust_store(
        {
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
            "default_artifact_types": ["scope_grant"],
        },
        base_dir=tmp_path,
        required_artifact_type="scope_grant",
    )
    status_store = build_trust_store(
        {
            "keys": {
                status_keys["public_key_ref"]: {
                    "public_key_pem": status_keys["public_key_pem"],
                    "public_key_ref": status_keys["public_key_ref"],
                    "status": "active",
                    "algorithm": "Ed25519",
                    "authorized_artifact_types": ["scope_grant_status"],
                }
            },
            "revoked_key_ids": [],
            "default_artifact_types": ["scope_grant_status"],
        },
        base_dir=tmp_path,
        required_artifact_type="scope_grant_status",
    )
    manifest_store = build_trust_store(
        {
            "keys": {
                manifest_keys["public_key_ref"]: {
                    "public_key_pem": manifest_keys["public_key_pem"],
                    "public_key_ref": manifest_keys["public_key_ref"],
                    "status": "active",
                    "algorithm": "Ed25519",
                    "authorized_artifact_types": ["scope_authorization_manifest"],
                }
            },
            "revoked_key_ids": [],
            "default_artifact_types": ["scope_authorization_manifest"],
        },
        base_dir=tmp_path,
        required_artifact_type="scope_authorization_manifest",
    )
    manifest = build_test_authorization_manifest(signer_keys=manifest_keys)
    return {
        "issuer_keys": issuer_keys,
        "status_keys": status_keys,
        "manifest_keys": manifest_keys,
        "issuer_store": issuer_store,
        "status_store": status_store,
        "manifest_store": manifest_store,
        "manifest": manifest,
        "trust_root": manifest["manifest_hash"],
    }


def sign_status(
    status: dict[str, Any],
    status_keys: dict[str, str],
) -> dict[str, Any]:
    payload = dict(status)
    payload["issuer"] = {
        "issuer_identity": "scope-status",
        "issuer_key_id": status_keys["public_key_ref"],
    }
    if "attestation_hash" not in payload:
        body = {
            k: v
            for k, v in payload.items()
            if k
            not in {
                "attestation_hash",
                "attestation_signature",
                "signed_payload_hash",
            }
        }
        payload["attestation_hash"] = hash_object(body)
    payload["signed_payload_hash"] = payload["attestation_hash"]
    priv = Path(status_keys["private_key_path"]).read_bytes()
    payload["attestation_signature"] = sign_payload_hash_ed25519(
        priv, payload["attestation_hash"]
    )
    return payload


def make_signed_grant(
    kit: dict[str, Any],
    *,
    artifacts: dict[str, Any] | None = None,
    envelope: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return (grant, ledger_status, source_artifacts)."""
    arts = artifacts or make_source_artifacts()
    env = envelope or legacy_scope_to_envelope(
        approved_scope="protocol_draft",
        allowed_tools=["protocol_editor.draft_change"],
        blocked_tools=["robot_queue.submit"],
        target={"type": "protocol", "protocol_id": "protocol-v3"},
        environment={"tenant_id": "tenant-a"},
        cardinality={"mode": "single", "maximum_uses": 1, "maximum_items": 1},
        constraints={"protocol_version": "protocol-v3"},
    )
    grant: dict[str, Any] = {
        "grant_id": "SCOPE-GRANT-INST-1",
        "grant_version": "2.0.0",
        "created_at": "2026-01-01T00:00:00Z",
        "authorization": {
            "approved_scope": "protocol_draft",
            "allowed_tools": list(env["allowed_tools"]),
            "blocked_tools": list(env["blocked_tools"]),
            "authorization_envelope": env,
        },
        "authorization_schema_version": ENVELOPE_VERSION,
        "authorization_schema_hash": authorization_envelope_schema_hash(),
        "issuer": {
            "issuer_identity": "scope-test",
            "issuer_key_id": kit["issuer_keys"]["public_key_ref"],
        },
        "source": {
            "packet_id": arts["packet"]["packet_id"],
            "packet_hash": arts["packet"]["packet_hash"],
            "decision_id": arts["decision"]["decision_id"],
            "decision_hash": arts["decision"]["decision_hash"],
            "akta_record_id": arts["record"]["record_id"],
            "akta_record_hash": arts["record"]["record_hash"],
            "review_trigger_id": arts["review_trigger"]["review_trigger_id"],
            "review_trigger_hash": arts["review_trigger"]["review_trigger_hash"],
            "scope_decision_id": arts["scope_decision"]["scope_decision_id"],
            "scope_decision_hash": arts["scope_decision"]["scope_decision_hash"],
        },
        "provenance": {"scope_trust_root_hash": kit["trust_root"]},
        "constraints": {"single_use": True, "tenant_id": "tenant-a"},
        "expiration": {
            "absolute_expiration": "2030-01-01T00:00:00Z",
            "expires_after": [],
        },
        "signature_algorithm": "Ed25519",
    }
    if overrides:
        # Deep-merge common nested maps when provided.
        for key, value in overrides.items():
            if (
                key in {"constraints", "expiration", "provenance", "source", "authorization"}
                and isinstance(value, dict)
                and isinstance(grant.get(key), dict)
            ):
                merged = dict(grant[key])
                merged.update(value)
                grant[key] = merged
            else:
                grant[key] = value
    grant = _contracts().attach_hash(grant, "grant_hash")
    grant["signed_payload_hash"] = grant["grant_hash"]
    priv = Path(kit["issuer_keys"]["private_key_path"]).read_bytes()
    grant["grant_signature"] = sign_payload_hash_ed25519(priv, grant["grant_hash"])

    status = {
        "grant_id": grant["grant_id"],
        "status": "active",
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cardinality_remaining": 1,
        "grant_hash": grant["grant_hash"],
        "scope_trust_root_hash": kit["trust_root"],
        "tenant_id": "tenant-a",
        "ledger_sequence": 1,
        "authorization_schema_version": ENVELOPE_VERSION,
        "authorization_schema_hash": authorization_envelope_schema_hash(),
    }
    status = sign_status(status, kit["status_keys"])
    return grant, status, arts
