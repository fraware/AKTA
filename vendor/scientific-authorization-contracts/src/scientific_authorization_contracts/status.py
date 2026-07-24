"""Grant status enum, counters, and signed attestation builders/validators."""

from __future__ import annotations

from typing import Any, Mapping

from scientific_authorization_contracts.errors import EnvelopeValidationError
from scientific_authorization_contracts.hashing import compute_hash
from scientific_authorization_contracts.loaders import load_schema

STATUS_VERSION = "scope-grant-status-v1"

# Operational + attestation status values (2.2).
STATUS_ACTIVE = "active"
STATUS_EXHAUSTED = "exhausted"
STATUS_REVOKED = "revoked"
STATUS_EXPIRED = "expired"
STATUS_SUPERSEDED = "superseded"
STATUS_INVALID = "invalid"
STATUS_NOT_FOUND = "not_found"

# Legacy aliases mapped at read boundaries.
_LEGACY_STATUS_MAP = {
    "consumed": STATUS_EXHAUSTED,
    "used": STATUS_EXHAUSTED,
}

TERMINAL_STATUSES = frozenset(
    {
        STATUS_EXHAUSTED,
        STATUS_REVOKED,
        STATUS_EXPIRED,
        STATUS_SUPERSEDED,
        STATUS_INVALID,
    }
)

AUTHORITATIVE_STATUSES = frozenset(
    {
        STATUS_ACTIVE,
        STATUS_EXHAUSTED,
        STATUS_REVOKED,
        STATUS_EXPIRED,
        STATUS_SUPERSEDED,
        STATUS_INVALID,
        STATUS_NOT_FOUND,
    }
)


def normalize_status(status: str) -> str:
    raw = str(status)
    return _LEGACY_STATUS_MAP.get(raw, raw)


def load_status_schema() -> dict[str, Any]:
    return load_schema("scope_grant_status.v1.schema.json")


def load_status_attestation_schema() -> dict[str, Any]:
    return load_schema("scope_grant_status_attestation.v1.schema.json")


def derive_lifecycle_status(
    *,
    revoked: bool = False,
    expired: bool = False,
    superseded: bool = False,
    invalid: bool = False,
    use_count: int = 0,
    maximum_uses: int | None = None,
) -> str:
    """Derive status from ledger facts (exhausted replaces used/consumed)."""
    if invalid:
        return STATUS_INVALID
    if revoked:
        return STATUS_REVOKED
    if superseded:
        return STATUS_SUPERSEDED
    if expired:
        return STATUS_EXPIRED
    if maximum_uses is not None and use_count >= int(maximum_uses):
        return STATUS_EXHAUSTED
    return STATUS_ACTIVE


def status_counters(
    *,
    use_count: int,
    maximum_uses: int | None,
    last_use_event_id: str | None = None,
    last_use_sequence: int | None = None,
) -> dict[str, Any]:
    remaining: int | None
    if maximum_uses is None:
        remaining = None
    else:
        remaining = max(0, int(maximum_uses) - int(use_count))
    return {
        "use_count": int(use_count),
        "maximum_uses": maximum_uses,
        "remaining_uses": remaining,
        "cardinality_remaining": remaining,
        "last_use_event_id": last_use_event_id,
        "last_use_sequence": last_use_sequence,
    }


def build_status_attestation_payload(
    *,
    grant_id: str,
    grant_hash: str,
    status: str,
    checked_at: str,
    trust_root_hash: str | None = None,
    audience: str | None = None,
    use_count: int = 0,
    maximum_uses: int | None = None,
    remaining_uses: int | None = None,
    last_use_event_id: str | None = None,
    last_use_sequence: int | None = None,
    flags: dict[str, Any] | None = None,
    issuer_identity: str | None = None,
    issuer_key_id: str | None = None,
) -> dict[str, Any]:
    """Unsigned attestation body prior to hash/sign."""
    normalized = normalize_status(status)
    if normalized not in AUTHORITATIVE_STATUSES:
        raise EnvelopeValidationError(f"Unknown grant status: {status}")
    if not grant_hash.startswith("sha256:"):
        raise EnvelopeValidationError("grant_hash must be sha256:...")
    counters = status_counters(
        use_count=use_count,
        maximum_uses=maximum_uses,
        last_use_event_id=last_use_event_id,
        last_use_sequence=last_use_sequence,
    )
    if remaining_uses is not None:
        counters["remaining_uses"] = remaining_uses
        counters["cardinality_remaining"] = remaining_uses
    payload: dict[str, Any] = {
        "status_version": STATUS_VERSION,
        "grant_id": grant_id,
        "grant_hash": grant_hash,
        "status": normalized,
        "checked_at": checked_at,
        "use_count": counters["use_count"],
        "maximum_uses": counters["maximum_uses"],
        "remaining_uses": counters["remaining_uses"],
        "cardinality_remaining": counters["cardinality_remaining"],
        "last_use_event_id": counters["last_use_event_id"],
        "last_use_sequence": counters["last_use_sequence"],
        "flags": dict(flags or {}),
    }
    if trust_root_hash is not None:
        payload["trust_root_hash"] = trust_root_hash
    if audience is not None:
        payload["audience"] = audience
    if issuer_identity is not None or issuer_key_id is not None:
        payload["issuer"] = {
            "issuer_identity": issuer_identity or "scope-authorization-service",
            "issuer_key_id": issuer_key_id or "",
        }
    return payload


def validate_status_attestation_payload(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("status_version") != STATUS_VERSION:
        errors.append("status_version must be scope-grant-status-v1")
    if not payload.get("grant_id"):
        errors.append("grant_id required")
    grant_hash = payload.get("grant_hash")
    if not isinstance(grant_hash, str) or not grant_hash.startswith("sha256:"):
        errors.append("grant_hash required")
    status = normalize_status(str(payload.get("status") or ""))
    if status not in AUTHORITATIVE_STATUSES:
        errors.append(f"invalid status: {payload.get('status')}")
    if not payload.get("checked_at"):
        errors.append("checked_at required")
    return errors


def require_valid_status_attestation(payload: Mapping[str, Any]) -> None:
    errors = validate_status_attestation_payload(payload)
    if errors:
        raise EnvelopeValidationError(
            "Invalid status attestation: " + "; ".join(errors),
            errors=list(errors),
        )


def attestation_payload_hash(payload: Mapping[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k not in ("status_hash", "status_signature", "signature_algorithm", "signed_payload_hash")}
    return compute_hash(body)
