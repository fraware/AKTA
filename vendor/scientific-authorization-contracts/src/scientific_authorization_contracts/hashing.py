"""Canonical grant hashing shared by SCOPE and AKTA consumers."""

from __future__ import annotations

import hashlib
import json
from typing import Any

HASH_FIELDS = frozenset(
    {
        "packet_hash",
        "decision_hash",
        "grant_hash",
        "event_hash",
        "previous_event_hash",
        "manifest_hash",
        "resolution_hash",
        "status_hash",
        "delegation_hash",
    }
)

SIGNATURE_FIELDS = frozenset(
    {
        "decision_signature",
        "grant_signature",
        "status_signature",
        "signature_algorithm",
        "signed_payload_hash",
        "manifest_signature",
        "manifest_signature_algorithm",
        "manifest_signature_key_id",
        "attestation_signature",
        "reviewer_public_key_path",
        "resolver_signature",
        "delegation_signature",
    }
)

# Runtime-only markers excluded from canonical hashing (not persistence fields).
RUNTIME_MARKER_FIELDS = frozenset(
    {
        "_untrusted_parse",
    }
)

NON_HASHED_FIELDS = HASH_FIELDS | SIGNATURE_FIELDS | RUNTIME_MARKER_FIELDS


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def strip_hash_fields(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k not in NON_HASHED_FIELDS}


def compute_hash(data: dict[str, Any], *, field_name: str | None = None) -> str:
    payload = strip_hash_fields(data)
    if field_name and field_name in payload:
        del payload[field_name]
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def verify_hash(data: dict[str, Any], field_name: str) -> bool:
    if field_name not in data:
        return False
    return bool(data[field_name] == compute_hash(data, field_name=field_name))


def attach_hash(data: dict[str, Any], field_name: str) -> dict[str, Any]:
    result = dict(data)
    result[field_name] = compute_hash(result, field_name=field_name)
    return result
