"""Grant schemas, source-block validators, and finalized grant type markers."""

from __future__ import annotations

from typing import Any, Mapping, NewType

from scientific_authorization_contracts.errors import EnvelopeValidationError
from scientific_authorization_contracts.hashing import compute_hash
from scientific_authorization_contracts.loaders import load_schema

# Opaque bytes that are the signed persistence/transport artifact.
CanonicalGrantBytes = NewType("CanonicalGrantBytes", bytes)

# Mapping marker used by both SCOPE and AKTA; concrete freeze lives in SCOPE.
FinalizedGrant = Mapping[str, Any]

SOURCE_HASH_PATTERN_PREFIX = "sha256:"

REQUIRED_SOURCE_IDS = (
    "akta_record_id",
    "review_trigger_id",
    "packet_id",
    "decision_id",
)
REQUIRED_SOURCE_HASHES = (
    "akta_record_hash",
    "review_trigger_hash",
    "packet_hash",
    "decision_hash",
)
SESSION_SOURCE_IDS = ("session_id", "session_resolution_id")
SESSION_SOURCE_HASHES = ("session_resolution_hash",)
SESSION_SOURCE_LISTS = ("contributing_decision_ids", "contributing_decision_hashes")


def load_grant_schema() -> dict[str, Any]:
    return load_schema("scope_grant.v2.schema.json")


def _require_nonempty_str(source: dict[str, Any], key: str, errors: list[str]) -> None:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"source.{key} required")


def _require_hash(source: dict[str, Any], key: str, errors: list[str]) -> None:
    value = source.get(key)
    if not isinstance(value, str) or not value.startswith(SOURCE_HASH_PATTERN_PREFIX):
        errors.append(f"source.{key} must be a sha256:... digest")
    elif len(value) != len(SOURCE_HASH_PATTERN_PREFIX) + 64:
        errors.append(f"source.{key} must be sha256: + 64 hex chars")


def validate_source_block(
    source: dict[str, Any] | None,
    *,
    require_session: bool | None = None,
) -> list[str]:
    """
    Validate grant ``source`` hash bindings.

    Always requires AKTA record / trigger / packet / decision id+hash pairs.
    When ``session_id`` is present (or ``require_session``), also requires session
    resolution id/hash and contributing decision id/hash lists.
    """
    errors: list[str] = []
    if not isinstance(source, dict):
        return ["source must be an object"]
    for key in REQUIRED_SOURCE_IDS:
        _require_nonempty_str(source, key, errors)
    for key in REQUIRED_SOURCE_HASHES:
        _require_hash(source, key, errors)

    session = bool(source.get("session_id"))
    if require_session is True:
        session = True
    if require_session is False:
        session = False
    if session:
        for key in SESSION_SOURCE_IDS:
            _require_nonempty_str(source, key, errors)
        for key in SESSION_SOURCE_HASHES:
            # Accept either session_resolution_hash or legacy resolution_hash.
            if key == "session_resolution_hash":
                if not (
                    (
                        isinstance(source.get("session_resolution_hash"), str)
                        and source["session_resolution_hash"].startswith(
                            SOURCE_HASH_PATTERN_PREFIX
                        )
                    )
                    or (
                        isinstance(source.get("resolution_hash"), str)
                        and source["resolution_hash"].startswith(SOURCE_HASH_PATTERN_PREFIX)
                    )
                ):
                    errors.append(
                        "source.session_resolution_hash (or resolution_hash) required"
                    )
            else:
                _require_hash(source, key, errors)
        ids = source.get("contributing_decision_ids")
        hashes = source.get("contributing_decision_hashes")
        if not isinstance(ids, (list, tuple)) or not ids:
            errors.append("source.contributing_decision_ids required (non-empty)")
        if not isinstance(hashes, (list, tuple)) or not hashes:
            errors.append("source.contributing_decision_hashes required (non-empty)")
        elif isinstance(ids, (list, tuple)) and len(ids) != len(hashes):
            errors.append(
                "source.contributing_decision_ids/hashes length mismatch"
            )
        else:
            for h in hashes or []:
                if not isinstance(h, str) or not h.startswith(SOURCE_HASH_PATTERN_PREFIX):
                    errors.append("source.contributing_decision_hashes must be sha256:...")
                    break
    return errors


def require_valid_source_block(
    source: dict[str, Any] | None,
    *,
    require_session: bool | None = None,
) -> None:
    errors = validate_source_block(source, require_session=require_session)
    if errors:
        raise EnvelopeValidationError(
            "Invalid grant source block: " + "; ".join(errors),
            errors=errors,
        )


def source_block_hash(source: Mapping[str, Any]) -> str:
    """Hash of the source block alone (for binding checks; not a re-canonicalize of AKTA)."""
    return compute_hash(dict(source))


def mark_untrusted_grant_dict(grant: dict[str, Any]) -> dict[str, Any]:
    """Mark a parse-to-dict grant as untrusted until CanonicalGrantBytes re-verify."""
    out = dict(grant)
    out["_untrusted_parse"] = True
    return out


def is_untrusted_grant_dict(grant: Mapping[str, Any]) -> bool:
    return bool(grant.get("_untrusted_parse"))
