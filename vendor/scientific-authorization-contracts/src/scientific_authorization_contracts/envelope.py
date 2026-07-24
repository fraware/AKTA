"""AuthorizationEnvelope model and algebra (authoritative for SCOPE/AKTA)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from scientific_authorization_contracts.cardinality import (
    cardinality_intersection,
    cardinality_is_narrower_or_equal,
    normalize_cardinality,
)
from scientific_authorization_contracts.constraints import (
    constraint_contains,
    constraint_difference,
    constraint_intersection,
    validate_constraints,
)
from scientific_authorization_contracts.environments import (
    environment_intersection,
    environment_is_narrower_or_equal,
    normalize_environment,
)
from scientific_authorization_contracts.errors import (
    EnvelopeConflictError,
    EnvelopeValidationError,
)
from scientific_authorization_contracts.expiration import (
    expiration_intersection,
    expiration_is_shorter_or_equal,
    normalize_expiration,
)
from scientific_authorization_contracts.loaders import (
    ENVELOPE_VERSION,
    capability_families,
    family_operations,
    legacy_scope_migration,
    load_schema,
    responsibility_rank,
)
from scientific_authorization_contracts.operations import (
    narrower_operation,
    operation_is_narrower_or_equal,
)
from scientific_authorization_contracts.targets import (
    normalize_target,
    target_intersection,
    target_is_narrower_or_equal,
)

CAPABILITY_ID_RE = re.compile(r"^CAP-[0-9A-Fa-f]{32}$")


def new_capability_id() -> str:
    return f"CAP-{uuid.uuid4().hex.upper()}"


def validate_envelope_dict(
    data: dict[str, Any], *, raise_on_error: bool = True
) -> list[str]:
    errors: list[str] = []
    version = data.get("envelope_version") or ENVELOPE_VERSION
    if version != ENVELOPE_VERSION:
        errors.append(f"Unsupported envelope_version: {version}")
    family = data.get("family")
    if family not in capability_families():
        errors.append(f"Unknown capability family: {family}")
    else:
        ops = family_operations().get(str(family), [])
        if data.get("operation") not in ops:
            errors.append(
                f"Unknown operation '{data.get('operation')}' for family '{family}'"
            )
    ceiling = data.get("responsibility_ceiling") or "R4_methodological_modification"
    if ceiling not in responsibility_rank():
        errors.append(f"Unknown responsibility_ceiling: {ceiling}")
    try:
        if "target" in data and data["target"] is not None:
            normalize_target(dict(data.get("target") or {}))
        if "cardinality" in data and data["cardinality"] is not None:
            normalize_cardinality(dict(data.get("cardinality") or {}))
        if "environment" in data and data["environment"] is not None:
            normalize_environment(dict(data.get("environment") or {}))
        if "expiration" in data and data["expiration"] is not None:
            normalize_expiration(dict(data.get("expiration") or {}))
        validate_constraints(dict(data.get("constraints") or {}))
    except (EnvelopeValidationError, EnvelopeConflictError) as exc:
        errors.append(str(exc))
    if errors and raise_on_error:
        raise EnvelopeValidationError("; ".join(errors), errors=errors)
    return errors


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
    cardinality: dict[str, Any] = field(
        default_factory=lambda: normalize_cardinality(None)
    )
    environment: dict[str, Any] = field(default_factory=dict)
    responsibility_ceiling: str = "R4_methodological_modification"
    constraints: dict[str, Any] = field(default_factory=dict)
    expiration: dict[str, Any] = field(
        default_factory=lambda: normalize_expiration(None)
    )

    def __post_init__(self) -> None:
        if self.envelope_version != ENVELOPE_VERSION:
            raise EnvelopeValidationError(
                f"Unsupported envelope_version: {self.envelope_version}"
            )
        if self.family not in capability_families():
            raise EnvelopeValidationError(f"Unknown capability family: {self.family}")
        ops = family_operations().get(self.family, [])
        if self.operation not in ops:
            raise EnvelopeValidationError(
                f"Unknown operation '{self.operation}' for family '{self.family}'"
            )
        if self.responsibility_ceiling not in responsibility_rank():
            raise EnvelopeValidationError(
                f"Unknown responsibility_ceiling: {self.responsibility_ceiling}"
            )
        self.target = normalize_target(self.target) if self.target else {}
        self.cardinality = normalize_cardinality(self.cardinality)
        self.environment = normalize_environment(self.environment)
        self.expiration = normalize_expiration(self.expiration)
        # Empty allowlist is deny-all; absent is represented as [] after construction.
        self.allowed_tools = sorted(set(self.allowed_tools))
        self.blocked_tools = sorted(set(self.blocked_tools))
        validate_constraints(self.constraints)

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope_version": self.envelope_version,
            "capability_id": self.capability_id,
            "family": self.family,
            "operation": self.operation,
            "target": dict(self.target),
            "allowed_tools": list(self.allowed_tools),
            "blocked_tools": list(self.blocked_tools),
            "cardinality": dict(self.cardinality),
            "environment": dict(self.environment),
            "responsibility_ceiling": self.responsibility_ceiling,
            "constraints": dict(self.constraints),
            "expiration": dict(self.expiration),
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        validate: bool = True,
        require_allowlist_key: bool = False,
    ) -> AuthorizationEnvelope:
        if require_allowlist_key and "allowed_tools" not in data:
            raise EnvelopeValidationError(
                "absent allowed_tools is invalid; use [] for deny-all"
            )
        del validate  # validation happens in __post_init__
        payload = {
            "envelope_version": str(data.get("envelope_version") or ENVELOPE_VERSION),
            "capability_id": str(data.get("capability_id") or new_capability_id()),
            "family": str(data["family"]),
            "operation": str(data["operation"]),
            "target": dict(data.get("target") or {}),
            "allowed_tools": list(data.get("allowed_tools") or []),
            "blocked_tools": list(data.get("blocked_tools") or []),
            "cardinality": dict(data.get("cardinality") or {"mode": "unbounded"}),
            "environment": dict(data.get("environment") or {}),
            "responsibility_ceiling": str(
                data.get("responsibility_ceiling") or "R4_methodological_modification"
            ),
            "constraints": dict(data.get("constraints") or {}),
            "expiration": dict(data.get("expiration") or {}),
        }
        return cls(**payload)


def _responsibility_is_lower_or_equal(a: str, b: str) -> bool:
    ranks = responsibility_rank()
    return ranks.get(a, 99) <= ranks.get(b, 99)


def envelope_is_narrower(
    inner: AuthorizationEnvelope | dict[str, Any],
    outer: AuthorizationEnvelope | dict[str, Any],
) -> bool:
    """True if inner is a capability-set subset of outer."""
    inner_env = (
        inner
        if isinstance(inner, AuthorizationEnvelope)
        else AuthorizationEnvelope.from_dict(inner, validate=False)
    )
    outer_env = (
        outer
        if isinstance(outer, AuthorizationEnvelope)
        else AuthorizationEnvelope.from_dict(outer, validate=False)
    )
    if inner_env.family != outer_env.family:
        return False
    if not operation_is_narrower_or_equal(
        inner_env.family, inner_env.operation, outer_env.operation
    ):
        return False
    if not target_is_narrower_or_equal(inner_env.target, outer_env.target):
        return False
    if not set(inner_env.allowed_tools).issubset(set(outer_env.allowed_tools)):
        if "*" not in outer_env.allowed_tools:
            return False
    if not set(outer_env.blocked_tools).issubset(set(inner_env.blocked_tools)):
        return False
    if not cardinality_is_narrower_or_equal(inner_env.cardinality, outer_env.cardinality):
        return False
    if not environment_is_narrower_or_equal(inner_env.environment, outer_env.environment):
        return False
    if not _responsibility_is_lower_or_equal(
        inner_env.responsibility_ceiling, outer_env.responsibility_ceiling
    ):
        return False
    if not expiration_is_shorter_or_equal(inner_env.expiration, outer_env.expiration):
        return False
    if not constraint_contains(outer_env.constraints, inner_env.constraints):
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
    return envelope_contains(granted, requested)


def compare_envelopes(
    a: AuthorizationEnvelope | dict[str, Any],
    b: AuthorizationEnvelope | dict[str, Any],
) -> str:
    """Return 'equal', 'narrower', 'wider', or 'incomparable'."""
    left = a if isinstance(a, AuthorizationEnvelope) else AuthorizationEnvelope.from_dict(a, validate=False)
    right = b if isinstance(b, AuthorizationEnvelope) else AuthorizationEnvelope.from_dict(b, validate=False)
    if left.family != right.family:
        return "incomparable"
    a_in_b = envelope_is_narrower(left, right)
    b_in_a = envelope_is_narrower(right, left)
    if a_in_b and b_in_a:
        return "equal"
    if a_in_b:
        return "narrower"
    if b_in_a:
        return "wider"
    return "incomparable"


def envelope_intersection(
    a: AuthorizationEnvelope | dict[str, Any],
    b: AuthorizationEnvelope | dict[str, Any],
) -> AuthorizationEnvelope:
    left = a if isinstance(a, AuthorizationEnvelope) else AuthorizationEnvelope.from_dict(a, validate=False)
    right = b if isinstance(b, AuthorizationEnvelope) else AuthorizationEnvelope.from_dict(b, validate=False)
    if left.family != right.family:
        raise EnvelopeConflictError(
            "Cross-family envelopes are incomparable",
            conflict={
                "type": "family_mismatch",
                "left_family": left.family,
                "right_family": right.family,
                "left_capability_id": left.capability_id,
                "right_capability_id": right.capability_id,
                "result": "incomparable",
            },
        )

    operation = narrower_operation(left.family, left.operation, right.operation)
    target = target_intersection(left.target, right.target)
    env = environment_intersection(left.environment, right.environment)

    if "*" in left.allowed_tools:
        allowed = sorted(set(right.allowed_tools))
    elif "*" in right.allowed_tools:
        allowed = sorted(set(left.allowed_tools))
    else:
        allowed = sorted(set(left.allowed_tools) & set(right.allowed_tools))

    blocked = sorted(set(left.blocked_tools) | set(right.blocked_tools))
    allowed = [t for t in allowed if t not in blocked]

    ranks = responsibility_rank()
    a_resp = ranks.get(left.responsibility_ceiling, 99)
    b_resp = ranks.get(right.responsibility_ceiling, 99)
    responsibility = (
        left.responsibility_ceiling
        if a_resp <= b_resp
        else right.responsibility_ceiling
    )

    return AuthorizationEnvelope(
        family=left.family,
        operation=operation,
        target=target,
        allowed_tools=allowed,
        blocked_tools=blocked,
        cardinality=cardinality_intersection(left.cardinality, right.cardinality),
        environment=env,
        responsibility_ceiling=responsibility,
        constraints=constraint_intersection(left.constraints, right.constraints),
        expiration=expiration_intersection(left.expiration, right.expiration),
    )


def envelope_difference(
    a: AuthorizationEnvelope | dict[str, Any],
    b: AuthorizationEnvelope | dict[str, Any],
) -> dict[str, Any]:
    left = a if isinstance(a, AuthorizationEnvelope) else AuthorizationEnvelope.from_dict(a, validate=False)
    right = b if isinstance(b, AuthorizationEnvelope) else AuthorizationEnvelope.from_dict(b, validate=False)
    return {
        "same_family": left.family == right.family,
        "result": compare_envelopes(left, right),
        "family": left.family
        if left.family == right.family
        else {"left": left.family, "right": right.family},
        "tools_only_in_left": sorted(set(left.allowed_tools) - set(right.allowed_tools)),
        "tools_only_in_right": sorted(set(right.allowed_tools) - set(left.allowed_tools)),
        "blocked_only_in_left": sorted(set(left.blocked_tools) - set(right.blocked_tools)),
        "operation_left": left.operation,
        "operation_right": right.operation,
        "constraint_difference": constraint_difference(left.constraints, right.constraints),
        "contains_left_in_right": envelope_contains(right, left)
        if left.family == right.family
        else False,
        "contains_right_in_left": envelope_contains(left, right)
        if left.family == right.family
        else False,
    }


def intersect_approving_envelopes(
    envelopes: list[AuthorizationEnvelope],
) -> AuthorizationEnvelope:
    if not envelopes:
        raise EnvelopeValidationError("No approving envelopes to intersect")
    result = envelopes[0]
    for env in envelopes[1:]:
        result = envelope_intersection(result, env)
    return result


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
    single_use_scopes = {"single_validation_run_draft", "robot_queue_submission"}
    default_card = (
        {"mode": "single", "maximum_uses": 1, "maximum_items": 1}
        if scope_name in single_use_scopes
        else {"mode": "unbounded"}
    )
    return AuthorizationEnvelope(
        family=family,
        operation=operation,
        capability_id=capability_id or new_capability_id(),
        target=dict(target or {}),
        allowed_tools=list(allowed_tools if allowed_tools is not None else []),
        blocked_tools=list(blocked_tools or []),
        cardinality=dict(cardinality or default_card),
        environment=dict(environment or {}),
        responsibility_ceiling=responsibility_ceiling or "R4_methodological_modification",
        constraints=dict(constraints or {}),
        expiration=dict(expiration or {}),
    )


def load_envelope_schema() -> dict[str, Any]:
    return load_schema("authorization_envelope.v2.schema.json")
