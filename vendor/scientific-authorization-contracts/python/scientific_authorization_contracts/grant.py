"""Grant and grant-status validation against shared JSON Schemas."""

from __future__ import annotations

from typing import Any

from scientific_authorization_contracts.hashing import verify_hash

GRANT_V2_SCHEMA_NAME = "scope_grant.v2.schema.json"
GRANT_STATUS_SCHEMA_NAME = "scope_grant_status.v1.schema.json"


class GrantValidationError(ValueError):
    """Grant or grant-status payload failed shared-schema validation."""

    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        self.errors = list(errors or [message])
        super().__init__(message)


def _jsonschema_validate(instance: dict[str, Any], schema_name: str) -> list[str]:
    from scientific_authorization_contracts import load_schema

    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise GrantValidationError(
            "jsonschema is required for grant validation"
        ) from exc

    schema = load_schema(schema_name)
    validator_cls = jsonschema.Draft202012Validator
    validator = validator_cls(schema)
    return [
        f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
        for err in validator.iter_errors(instance)
    ]


def validate_grant(
    grant: dict[str, Any],
    *,
    require_hash: bool = True,
    raise_on_error: bool = True,
) -> list[str]:
    """Validate a SCOPE grant against ``scope-grant-v2`` (+ optional grant_hash)."""
    errors = _jsonschema_validate(grant, GRANT_V2_SCHEMA_NAME)
    if require_hash and "grant_hash" in grant and not verify_hash(grant, "grant_hash"):
        errors.append("grant_hash mismatch (invalid or tampered grant payload)")
    if raise_on_error and errors:
        raise GrantValidationError("; ".join(errors), errors=errors)
    return errors


def validate_grant_status(
    status: dict[str, Any],
    *,
    raise_on_error: bool = True,
) -> list[str]:
    """Validate a grant-status attestation against ``scope-grant-status-v1``."""
    errors = _jsonschema_validate(status, GRANT_STATUS_SCHEMA_NAME)
    if raise_on_error and errors:
        raise GrantValidationError("; ".join(errors), errors=errors)
    return errors


__all__ = [
    "GRANT_STATUS_SCHEMA_NAME",
    "GRANT_V2_SCHEMA_NAME",
    "GrantValidationError",
    "validate_grant",
    "validate_grant_status",
]
