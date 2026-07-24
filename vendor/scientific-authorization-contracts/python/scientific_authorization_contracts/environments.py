"""Recognized environment bindings; unknown fields fail closed."""

from __future__ import annotations

from typing import Any

from scientific_authorization_contracts.errors import (
    EnvelopeConflictError,
    EnvelopeValidationError,
)

KNOWN_ENVIRONMENT_FIELDS = frozenset(
    {
        "tenant_id",
        "project_id",
        "deployment_id",
        "domain_overlay",
        "facility_id",
        "jurisdiction",
        "data_classification",
    }
)

_EXTENSION_SCHEMAS: dict[str, dict[str, Any]] = {}


def register_environment_extension(field: str, schema: dict[str, Any] | None = None) -> None:
    _EXTENSION_SCHEMAS[field] = dict(schema or {})


def normalize_environment(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(raw or {})
    unknown = [
        key
        for key in data
        if key not in KNOWN_ENVIRONMENT_FIELDS and key not in _EXTENSION_SCHEMAS
    ]
    if unknown:
        raise EnvelopeValidationError(
            f"Unknown environment fields fail closed: {sorted(unknown)}"
        )
    return data


def environment_is_narrower_or_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if not b:
        return True
    a_n = normalize_environment(a)
    b_n = normalize_environment(b)
    for key, value in b_n.items():
        if key not in a_n or a_n[key] != value:
            return False
    return True


def environment_intersection(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    a_n = normalize_environment(a)
    b_n = normalize_environment(b)
    result: dict[str, Any] = {}
    for key in set(a_n) | set(b_n):
        if key in a_n and key in b_n and a_n[key] != b_n[key]:
            raise EnvelopeConflictError(
                f"Incompatible environment binding for '{key}'",
                conflict={
                    "type": "environment_conflict",
                    "key": key,
                    "left": a_n[key],
                    "right": b_n[key],
                },
            )
        result[key] = a_n[key] if key in a_n else b_n[key]
    return result
