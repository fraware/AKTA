"""Shared authorization capability envelopes (scientific-authorization-envelope-v2).

AKTA no longer defines an independent capability-envelope vocabulary.
Security-critical comparison uses EXACT shared fields only:
envelope_version, capability_id, family, operation, target, allowed_tools,
blocked_tools, cardinality, environment, responsibility_ceiling, constraints,
expiration.

Legacy scalar adapters exist only for unit tests and migration tooling.
"""

from __future__ import annotations

from typing import Any

from akta.errors import GrantVerificationError
from akta.shared_contracts import (
    ENVELOPE_VERSION,
    _contracts,
    authorization_envelope_schema_hash,
    authorization_schema_provenance,
    capability_families,
    family_operations,
)


# Lazy-compatible frozenset: callers may import CAPABILITY_FAMILIES at module load.
def _families() -> frozenset[str]:
    return capability_families()


class _FamilyProxy(frozenset):
    """Proxy so ``x in CAPABILITY_FAMILIES`` resolves shared vocabulary at use time."""

    def __contains__(self, item: object) -> bool:  # type: ignore[override]
        return item in _families()

    def __iter__(self):  # type: ignore[override]
        return iter(_families())

    def __len__(self) -> int:  # type: ignore[override]
        return len(_families())


CAPABILITY_FAMILIES: frozenset[str] = _FamilyProxy()  # type: ignore[assignment]


def _api():
    return _contracts()


def get_envelope_version() -> str:
    return ENVELOPE_VERSION


def get_capability_families() -> frozenset[str]:
    return capability_families()


def extract_capability_envelope(scope_grant: dict[str, Any]) -> dict[str, Any] | None:
    """Return shared authorization envelope from grant root or authorization block.

    Accepts only shared field names. Looks for ``authorization_envelope`` (v2)
    or legacy ``capability_envelope`` key that already uses shared fields.
    """
    auth = scope_grant.get("authorization") or {}
    for key in ("authorization_envelope", "capability_envelope"):
        envelope = scope_grant.get(key) or auth.get(key)
        if isinstance(envelope, dict):
            return dict(envelope)
    return None


def validate_capability_envelope(envelope: dict[str, Any]) -> list[str]:
    """Return validation errors for a shared envelope (empty list = ok)."""
    return list(_api().validate_envelope_dict(envelope, raise_on_error=False))


def legacy_scope_to_envelope(
    *,
    approved_scope: str,
    allowed_tools: list[str] | None = None,
    blocked_tools: list[str] | None = None,
    expiration: str | dict[str, Any] | None = None,
    responsibility_ceiling: str = "R4_methodological_modification",
    target: dict[str, Any] | None = None,
    environment: dict[str, Any] | None = None,
    cardinality: dict[str, Any] | None = None,
    constraints: dict[str, Any] | None = None,
    # Deprecated kwargs retained for migration callers — NOT used in comparison.
    max_responsibility_level: str | None = None,
) -> dict[str, Any]:
    """Build a shared-schema envelope from a legacy scalar scope (compat only).

    Forbidden as an authorization driver in pilot/release/cross_repo/production.
    """
    short_map = {
        "R0": "R0_none",
        "R1": "R1_observation",
        "R2": "R2_interpretation",
        "R3": "R3_recommendation",
        "R4": "R4_methodological_modification",
        "R5": "R5_execution_preparation",
        "R6": "R6_physical_execution",
        "R7": "R7_publication",
        "R8": "R8_memory",
    }
    # Prefer explicit shared ceiling; map short R-levels from migration callers.
    if max_responsibility_level is not None and responsibility_ceiling == (
        "R4_methodological_modification"
    ):
        ceiling = short_map.get(max_responsibility_level, max_responsibility_level)
    else:
        ceiling = short_map.get(responsibility_ceiling, responsibility_ceiling)

    exp: dict[str, Any]
    if isinstance(expiration, dict):
        exp = dict(expiration)
    elif isinstance(expiration, str) and expiration:
        exp = {"absolute_expiration": expiration, "expires_after": []}
    else:
        exp = {"absolute_expiration": None, "expires_after": []}

    env = _api().envelope_from_legacy_scope(
        approved_scope,
        allowed_tools=allowed_tools,
        blocked_tools=blocked_tools,
        target=target,
        environment=environment,
        responsibility_ceiling=ceiling,
        expiration=exp,
        cardinality=cardinality,
        constraints=constraints,
    )
    return env.to_dict()


def envelope_narrows(
    granted: dict[str, Any],
    requested: dict[str, Any],
) -> bool:
    """True when requested is a set-inclusion narrowing of granted (same family).

    Checks: family, operation, target, allowed-tools subset, blocked-tools
    superset, cardinality, environment, responsibility ceiling, constraints,
    expiration. Unknown values invalidate (raise → treated as not covering).
    """
    try:
        return bool(_api().envelope_covers(granted, requested))
    except Exception:
        return False


def authorization_covers(
    *,
    granted_envelope: dict[str, Any] | None = None,
    requested_envelope: dict[str, Any] | None = None,
    granted_scope: str = "",
    requested_scope: str = "",
    scalar_covers: Any = None,
    allow_legacy_scalar: bool = False,
) -> tuple[bool, str]:
    """Primary authorization comparator: shared envelopes only by default.

    Returns ``(covers, comparator)`` where comparator is ``envelope`` or
    ``legacy_scalar`` (legacy only when explicitly allowed for unit/migration).
    """
    if granted_envelope is not None and requested_envelope is not None:
        return envelope_narrows(granted_envelope, requested_envelope), "envelope"
    if not allow_legacy_scalar:
        return False, "envelope_required"
    if scalar_covers is None:
        from akta.review_loop import grant_scope_covers_action

        scalar_covers = grant_scope_covers_action
    return bool(scalar_covers(granted_scope, requested_scope)), "legacy_scalar"


def resolve_grant_envelope(
    scope_grant: dict[str, Any],
    *,
    require_envelope: bool = False,
    allow_legacy_adapter: bool = True,
) -> dict[str, Any]:
    """Resolve shared envelope from grant or legacy scalar adapter.

    Raises GrantVerificationError when require_envelope and none present /
    legacy adapter disabled.
    """
    envelope = extract_capability_envelope(scope_grant)
    if envelope is not None:
        errors = validate_capability_envelope(envelope)
        if errors:
            raise GrantVerificationError("; ".join(errors), errors=errors)
        return envelope

    if require_envelope or not allow_legacy_adapter:
        raise GrantVerificationError(
            "authorization_envelope required; scalar scope ranks are not sufficient "
            "(P0-B)",
            errors=["authorization_envelope_missing"],
        )

    from akta.scope_contract import _scope_grant_approved_scope

    auth = scope_grant.get("authorization") or {}
    approved = _scope_grant_approved_scope(scope_grant) or ""
    if "allowed_tools" in scope_grant:
        tools: list[str] | None = list(scope_grant.get("allowed_tools") or [])
    elif "allowed_tools" in auth:
        tools = list(auth.get("allowed_tools") or [])
    else:
        tools = None
    if "blocked_tools" in scope_grant:
        blocked: list[str] | None = list(scope_grant.get("blocked_tools") or [])
    elif "blocked_tools" in auth:
        blocked = list(auth.get("blocked_tools") or [])
    else:
        blocked = None
    expires = scope_grant.get("expires_at") or auth.get("expires_at")
    exp_obj = scope_grant.get("expiration") or auth.get("expiration")
    return legacy_scope_to_envelope(
        approved_scope=approved,
        allowed_tools=tools,
        blocked_tools=blocked,
        expiration=exp_obj if isinstance(exp_obj, dict) else expires,
    )


def schema_identity() -> dict[str, str]:
    """Envelope + grant schema identity for cross-repo acceptance."""
    return {
        **authorization_schema_provenance(),
        "envelope_schema_hash": authorization_envelope_schema_hash(),
        "family_count": str(len(capability_families())),
        "operation_families": str(len(family_operations())),
    }
