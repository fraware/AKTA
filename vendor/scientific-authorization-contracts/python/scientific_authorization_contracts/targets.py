"""Discriminated target containment and intersection."""

from __future__ import annotations

from typing import Any

from scientific_authorization_contracts.errors import (
    EnvelopeConflictError,
    EnvelopeValidationError,
)
from scientific_authorization_contracts.loaders import target_types

# Required identifier keys per target type (missing → invalid in production algebra).
TARGET_REQUIRED_KEYS: dict[str, frozenset[str]] = {
    "protocol": frozenset({"protocol_id"}),
    "queue_entry": frozenset({"queue_entry_id"}),
    "instrument": frozenset({"instrument_id"}),
    "sample_set": frozenset({"sample_set_id"}),
    "dataset": frozenset({"dataset_id"}),
    "publication": frozenset({"publication_id"}),
    "memory_namespace": frozenset({"memory_namespace"}),
    "tool_permission": frozenset({"tool_id"}),
}

_INFERENCE_KEYS: tuple[tuple[str, str], ...] = (
    ("protocol_id", "protocol"),
    ("queue_entry_id", "queue_entry"),
    ("dataset_id", "dataset"),
    ("publication_id", "publication"),
    ("memory_namespace", "memory_namespace"),
    ("instrument_id", "instrument"),
    ("sample_set_id", "sample_set"),
    ("tool_id", "tool_permission"),
)


def normalize_target(
    raw: dict[str, Any] | None,
    *,
    require_identifiers: bool = False,
    allow_type_inference: bool = True,
) -> dict[str, Any]:
    data = dict(raw or {})
    if not data:
        return {}
    if "type" not in data:
        if not allow_type_inference:
            raise EnvelopeValidationError(
                "Target missing required 'type' (production inference disabled)"
            )
        inferred = None
        for key, target_type in _INFERENCE_KEYS:
            if key in data:
                inferred = target_type
                break
        if inferred is None:
            raise EnvelopeValidationError(
                "Target missing 'type' and no recognizable identifier fields"
            )
        data["type"] = inferred
    if data["type"] not in target_types():
        raise EnvelopeValidationError(f"Unknown target type: {data['type']}")
    if require_identifiers:
        required = TARGET_REQUIRED_KEYS.get(str(data["type"]), frozenset())
        missing = [key for key in required if not data.get(key)]
        if missing:
            raise EnvelopeValidationError(
                f"Target type '{data['type']}' missing required identifiers: {missing}"
            )
    return data


def target_is_narrower_or_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Typed target containment: inner may only add bindings or keep equal values."""
    if not b:
        return True
    if not a:
        return False
    a_n = normalize_target(a)
    b_n = normalize_target(b)
    if a_n.get("type") != b_n.get("type"):
        return False
    for key, value in b_n.items():
        if key not in a_n:
            return False
        if a_n[key] != value:
            return False
    return True


def target_intersection(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    if not a:
        return dict(b)
    if not b:
        return dict(a)
    a_n = normalize_target(a)
    b_n = normalize_target(b)
    if a_n.get("type") != b_n.get("type"):
        raise EnvelopeConflictError(
            "Incompatible target types",
            conflict={
                "type": "target_conflict",
                "left": a_n.get("type"),
                "right": b_n.get("type"),
            },
        )
    result: dict[str, Any] = {}
    for key in set(a_n) | set(b_n):
        if key in a_n and key in b_n and a_n[key] != b_n[key]:
            raise EnvelopeConflictError(
                f"Incompatible target binding for '{key}'",
                conflict={
                    "type": "target_conflict",
                    "key": key,
                    "left": a_n[key],
                    "right": b_n[key],
                },
            )
        result[key] = a_n[key] if key in a_n else b_n[key]
    return result
