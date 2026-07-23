"""Shared AuthorizationEnvelope model and partial-order comparison.

Authoritative for SCOPE and AKTA. Unknown family/operation/responsibility
values are invalid (never mapped onto a default broad/narrow rank).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from scientific_authorization_contracts import (
    ENVELOPE_VERSION,
    capability_families,
    family_operations,
    legacy_scope_migration,
    load_schema,
    responsibility_rank,
)

CAPABILITY_ID_RE = re.compile(r"^CAP-[0-9A-Fa-f]{32}$")

# Signature / hash fields that must not drive envelope equality.
_NON_COMPARE_KEYS = frozenset({"capability_id", "envelope_version"})


class EnvelopeValidationError(ValueError):
    """Envelope failed schema or vocabulary validation."""

    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        self.errors = list(errors or [message])
        super().__init__(message)


class EnvelopeConflictError(ValueError):
    """Envelopes cannot be safely intersected."""

    def __init__(self, message: str, *, conflict: dict[str, Any]) -> None:
        self.conflict = conflict
        super().__init__(message)


def new_capability_id() -> str:
    return f"CAP-{uuid.uuid4().hex.upper()}"


def _normalize_responsibility(level: str | None) -> str | None:
    """Accept full shared ids only; reject bare R0–R9 aliases in security paths."""
    if level is None:
        return None
    ranks = responsibility_rank()
    if level in ranks:
        return level
    return None


@dataclass
class AuthorizationEnvelope:
    """Capability-limited authorization unit (partial order, not total hierarchy)."""

    family: str
    operation: str
    envelope_version: str = ENVELOPE_VERSION
    capability_id: str = field(default_factory=new_capability_id)
    target: dict[str, Any] = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)
    blocked_tools: list[str] = field(default_factory=list)
    cardinality: dict[str, Any] = field(default_factory=lambda: {"mode": "single"})
    environment: dict[str, Any] = field(default_factory=dict)
    responsibility_ceiling: str = "R4_methodological_modification"
    constraints: dict[str, Any] = field(default_factory=dict)
    expiration: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        errors = validate_envelope_dict(self.to_dict(), raise_on_error=False)
        if errors:
            raise EnvelopeValidationError("; ".join(errors), errors=errors)
        self.allowed_tools = sorted(set(self.allowed_tools))
        self.blocked_tools = sorted(set(self.blocked_tools))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, validate: bool = True) -> AuthorizationEnvelope:
        payload = {
            "envelope_version": str(data.get("envelope_version") or ENVELOPE_VERSION),
            "capability_id": str(data.get("capability_id") or new_capability_id()),
            "family": str(data["family"]),
            "operation": str(data["operation"]),
            "target": dict(data.get("target") or {}),
            "allowed_tools": list(data.get("allowed_tools") or []),
            "blocked_tools": list(data.get("blocked_tools") or []),
            "cardinality": dict(data.get("cardinality") or {"mode": "single"}),
            "environment": dict(data.get("environment") or {}),
            "responsibility_ceiling": str(
                data.get("responsibility_ceiling") or "R4_methodological_modification"
            ),
            "constraints": dict(data.get("constraints") or {}),
            "expiration": dict(data.get("expiration") or {}),
        }
        if validate:
            errors = validate_envelope_dict(payload, raise_on_error=False)
            if errors:
                raise EnvelopeValidationError("; ".join(errors), errors=errors)
        # Bypass __post_init__ re-validation by constructing then assigning.
        obj = object.__new__(cls)
        for key, value in payload.items():
            setattr(obj, key, value)
        obj.allowed_tools = sorted(set(obj.allowed_tools))
        obj.blocked_tools = sorted(set(obj.blocked_tools))
        return obj


def validate_envelope_dict(
    envelope: dict[str, Any],
    *,
    raise_on_error: bool = True,
) -> list[str]:
    """Validate envelope against shared vocabulary + JSON Schema required fields."""
    errors: list[str] = []
    version = envelope.get("envelope_version")
    if version != ENVELOPE_VERSION:
        errors.append(
            f"envelope_version must be {ENVELOPE_VERSION!r}, got {version!r}"
        )

    cap_id = envelope.get("capability_id")
    if not isinstance(cap_id, str) or not CAPABILITY_ID_RE.match(cap_id):
        errors.append(f"invalid capability_id: {cap_id!r}")

    family = envelope.get("family")
    families = capability_families()
    if family not in families:
        errors.append(f"unknown family: {family!r}")

    operation = envelope.get("operation")
    ops = family_operations().get(str(family), []) if family in families else []
    if not operation:
        errors.append("operation is required")
    elif family in families and operation not in ops:
        errors.append(f"unknown operation {operation!r} for family {family!r}")

    if "target" not in envelope or not isinstance(envelope.get("target"), dict):
        errors.append("target must be an object")
    else:
        target = envelope["target"]
        if "type" not in target:
            errors.append("target.type is required")

    if "allowed_tools" not in envelope or not isinstance(envelope.get("allowed_tools"), list):
        errors.append("allowed_tools must be a list")
    elif any(not isinstance(t, str) or not t for t in envelope["allowed_tools"]):
        errors.append("allowed_tools entries must be non-empty strings")

    if "blocked_tools" not in envelope or not isinstance(envelope.get("blocked_tools"), list):
        errors.append("blocked_tools must be a list")
    elif any(not isinstance(t, str) or not t for t in envelope["blocked_tools"]):
        errors.append("blocked_tools entries must be non-empty strings")

    cardinality = envelope.get("cardinality")
    if not isinstance(cardinality, dict) or "mode" not in cardinality:
        errors.append("cardinality.mode is required")
    elif cardinality["mode"] not in ("single", "bounded", "unbounded"):
        errors.append(f"unknown cardinality.mode: {cardinality.get('mode')!r}")

    if "environment" not in envelope or not isinstance(envelope.get("environment"), dict):
        errors.append("environment must be an object")

    ceiling = envelope.get("responsibility_ceiling")
    if _normalize_responsibility(ceiling if isinstance(ceiling, str) else None) is None:
        errors.append(f"unknown responsibility_ceiling: {ceiling!r}")

    if "constraints" not in envelope or not isinstance(envelope.get("constraints"), dict):
        errors.append("constraints must be an object")

    if "expiration" not in envelope or not isinstance(envelope.get("expiration"), dict):
        errors.append("expiration must be an object")

    # Reject legacy AKTA field aliases in security-critical payloads.
    for forbidden in (
        "capability_family",
        "max_responsibility_level",
        "queue_allocation",
        "tool_permission",
        "scientific_memory",
        "legacy_approved_scope",
    ):
        if forbidden in envelope:
            errors.append(
                f"forbidden legacy field {forbidden!r}; use shared envelope vocabulary"
            )

    if raise_on_error and errors:
        raise EnvelopeValidationError("; ".join(errors), errors=errors)
    return errors


def _operation_rank(family: str, operation: str) -> int:
    ops = family_operations().get(family)
    if not ops or operation not in ops:
        raise EnvelopeValidationError(
            f"unknown operation {operation!r} for family {family!r}"
        )
    return ops.index(operation)


def _target_is_narrower_or_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if not b:
        return True
    for key, value in b.items():
        if key not in a or a[key] != value:
            return False
    return True


def _cardinality_is_narrower_or_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    mode_rank = {"single": 0, "bounded": 1, "unbounded": 2}
    a_mode = str(a.get("mode", "single"))
    b_mode = str(b.get("mode", "single"))
    if a_mode not in mode_rank or b_mode not in mode_rank:
        return False
    if mode_rank[a_mode] > mode_rank[b_mode]:
        return False
    a_max = a.get("maximum_uses", a.get("max"))
    b_max = b.get("maximum_uses", b.get("max"))
    if b_max is not None and a_max is not None and int(a_max) > int(b_max):
        return False
    if b_max is not None and a_max is None and a_mode != "single":
        return False
    return True


def _environment_is_narrower_or_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return _target_is_narrower_or_equal(a, b)


def _responsibility_is_lower_or_equal(a: str, b: str) -> bool:
    ranks = responsibility_rank()
    if a not in ranks or b not in ranks:
        return False
    return ranks[a] <= ranks[b]


def _expiration_is_shorter_or_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Compare absolute expiration; empty outer expiration is wider.

    Aligns with SCOPE authorization_envelope semantics used by conformance vectors.
    ``expires_after`` events are advisory in the partial order (more events does
    not alone determine narrower); absolute timestamps dominate when present.
    """
    if not b:
        return True
    if not a:
        return False
    a_abs = a.get("absolute_expiration")
    b_abs = b.get("absolute_expiration")
    if a_abs is None and b_abs is not None:
        return False
    if a_abs is not None and b_abs is not None and str(a_abs) > str(b_abs):
        return False
    # When only event lists are present (no absolute), require inner events to
    # be a non-empty subset-or-equal restriction via string ordering fallback.
    if a_abs is None and b_abs is None:
        a_events = a.get("expires_after")
        b_events = b.get("expires_after")
        if b_events and not a_events:
            return False
    return True


def _constraints_is_narrower_or_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Inner constraints must include all outer constraint bindings where both set."""
    if not b:
        return True
    for key, value in b.items():
        if key not in a:
            return False
        if a[key] != value:
            return False
    return True


def envelope_is_narrower(
    inner: AuthorizationEnvelope | dict[str, Any],
    outer: AuthorizationEnvelope | dict[str, Any],
) -> bool:
    """True if inner is a capability-set subset of outer."""
    inner_env = (
        inner
        if isinstance(inner, AuthorizationEnvelope)
        else AuthorizationEnvelope.from_dict(inner)
    )
    outer_env = (
        outer
        if isinstance(outer, AuthorizationEnvelope)
        else AuthorizationEnvelope.from_dict(outer)
    )
    if inner_env.family != outer_env.family:
        return False
    if _operation_rank(inner_env.family, inner_env.operation) > _operation_rank(
        outer_env.family, outer_env.operation
    ):
        return False
    if not _target_is_narrower_or_equal(inner_env.target, outer_env.target):
        return False
    if not set(inner_env.allowed_tools).issubset(set(outer_env.allowed_tools)):
        if "*" not in outer_env.allowed_tools:
            return False
    if not set(outer_env.blocked_tools).issubset(set(inner_env.blocked_tools)):
        return False
    if not _cardinality_is_narrower_or_equal(inner_env.cardinality, outer_env.cardinality):
        return False
    if not _environment_is_narrower_or_equal(inner_env.environment, outer_env.environment):
        return False
    if not _responsibility_is_lower_or_equal(
        inner_env.responsibility_ceiling, outer_env.responsibility_ceiling
    ):
        return False
    if not _constraints_is_narrower_or_equal(inner_env.constraints, outer_env.constraints):
        return False
    if not _expiration_is_shorter_or_equal(inner_env.expiration, outer_env.expiration):
        return False
    return True


def envelope_contains(
    outer: AuthorizationEnvelope | dict[str, Any],
    inner: AuthorizationEnvelope | dict[str, Any],
) -> bool:
    return envelope_is_narrower(inner, outer)


def envelope_covers(
    granted: AuthorizationEnvelope | dict[str, Any],
    requested: AuthorizationEnvelope | dict[str, Any],
) -> bool:
    """True when granted envelope authorizes the requested envelope."""
    return envelope_contains(granted, requested)


def compare_envelopes(
    inner: dict[str, Any],
    outer: dict[str, Any],
) -> dict[str, Any]:
    """Byte-stable conformance decision record for shared vectors."""
    try:
        narrower = envelope_is_narrower(inner, outer)
        decision = "narrower" if narrower else "not_narrower"
    except EnvelopeValidationError as exc:
        return {
            "decision": "invalid",
            "errors": list(exc.errors),
        }
    return {
        "decision": decision,
        "same_family": inner.get("family") == outer.get("family"),
        "family": inner.get("family") if inner.get("family") == outer.get("family") else {
            "inner": inner.get("family"),
            "outer": outer.get("family"),
        },
        "operation_inner": inner.get("operation"),
        "operation_outer": outer.get("operation"),
        "tools_subset": set(inner.get("allowed_tools") or []).issubset(
            set(outer.get("allowed_tools") or [])
        ),
        "blocked_superset": set(outer.get("blocked_tools") or []).issubset(
            set(inner.get("blocked_tools") or [])
        ),
    }


def envelope_from_legacy_scope(
    scope_name: str,
    *,
    allowed_tools: list[str] | None = None,
    blocked_tools: list[str] | None = None,
    target: dict[str, Any] | None = None,
    environment: dict[str, Any] | None = None,
    responsibility_ceiling: str | None = None,
    expiration: dict[str, Any] | None = None,
    cardinality: dict[str, Any] | None = None,
    constraints: dict[str, Any] | None = None,
    capability_id: str | None = None,
) -> AuthorizationEnvelope:
    """Migration adapter only — never a production authorization driver."""
    mapping = legacy_scope_migration()
    if scope_name not in mapping:
        raise EnvelopeValidationError(f"Unknown legacy approval scope: {scope_name}")
    family, operation = mapping[scope_name]
    default_target = {"type": "protocol"} if family == "protocol" else {"type": "dataset"}
    if family == "queue":
        default_target = {"type": "queue_entry"}
    elif family == "permissions":
        default_target = {"type": "tool_permission"}
    elif family == "memory":
        default_target = {"type": "memory_namespace"}
    elif family == "publication":
        default_target = {"type": "publication"}
    elif family == "execution":
        default_target = {"type": "instrument"}
    elif family in ("interpretation", "recommendation", "experiment_plan"):
        default_target = {"type": "protocol"}
    return AuthorizationEnvelope.from_dict(
        {
            "envelope_version": ENVELOPE_VERSION,
            "capability_id": capability_id or new_capability_id(),
            "family": family,
            "operation": operation,
            "target": dict(target or default_target),
            "allowed_tools": list(allowed_tools or []),
            "blocked_tools": list(blocked_tools or []),
            "cardinality": dict(cardinality or {"mode": "single"}),
            "environment": dict(environment or {}),
            "responsibility_ceiling": responsibility_ceiling
            or "R4_methodological_modification",
            "constraints": dict(constraints or {}),
            "expiration": dict(expiration or {"absolute_expiration": None, "expires_after": []}),
        }
    )


def load_envelope_schema() -> dict[str, Any]:
    return load_schema("authorization_envelope.v2.schema.json")
