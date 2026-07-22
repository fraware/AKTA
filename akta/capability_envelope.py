"""Authorization capability envelopes (directive §3).

Scalar SCOPE scope ranks remain as a backward-compatible adapter for existing
fixtures. New grant paths should carry a versioned capability_envelope; AKTA
may only narrow within the same capability_family (set inclusion).
"""

from __future__ import annotations

from typing import Any

from akta.errors import GrantVerificationError

ENVELOPE_VERSION = "akta-capability-envelope-v1.0"

CAPABILITY_FAMILIES: frozenset[str] = frozenset({
    "scientific_interpretation",
    "recommendation",
    "protocol",
    "experiment_plan",
    "queue_allocation",
    "tool_permission",
    "execution",
    "publication",
    "scientific_memory",
})

# Legacy scalar approved_scope → initial family mapping (compat adapter).
LEGACY_SCOPE_TO_FAMILY: dict[str, str] = {
    "draft_only": "scientific_interpretation",
    "protocol_draft": "protocol",
    "active_protocol_update": "protocol",
    "single_validation_plan": "experiment_plan",
    "single_validation_run_draft": "experiment_plan",
    "single_run_queue_priority": "queue_allocation",
    "robot_queue_submission": "execution",
    "execution_payload_preparation": "execution",
    "publication_claim": "publication",
    "scientific_memory_import": "scientific_memory",
}


def extract_capability_envelope(scope_grant: dict[str, Any]) -> dict[str, Any] | None:
    """Return capability_envelope from grant root or authorization block."""
    auth = scope_grant.get("authorization") or {}
    envelope = scope_grant.get("capability_envelope") or auth.get("capability_envelope")
    return dict(envelope) if isinstance(envelope, dict) else None


def validate_capability_envelope(envelope: dict[str, Any]) -> list[str]:
    """Return validation errors for an envelope (empty list = ok)."""
    errors: list[str] = []
    version = envelope.get("envelope_version")
    if version != ENVELOPE_VERSION:
        errors.append(
            f"capability_envelope.envelope_version must be {ENVELOPE_VERSION!r}, "
            f"got {version!r}"
        )
    family = envelope.get("capability_family")
    if family not in CAPABILITY_FAMILIES:
        errors.append(f"unknown capability_family: {family!r}")
    if not envelope.get("operation"):
        errors.append("capability_envelope.operation is required")
    if "allowed_tools" not in envelope:
        errors.append("capability_envelope.allowed_tools field is required")
    elif not isinstance(envelope.get("allowed_tools"), list):
        errors.append("capability_envelope.allowed_tools must be a list")
    level = envelope.get("max_responsibility_level")
    if not isinstance(level, str) or not level.startswith("R"):
        errors.append("capability_envelope.max_responsibility_level must look like R0–R9")
    return errors


def legacy_scope_to_envelope(
    *,
    approved_scope: str,
    allowed_tools: list[str] | None,
    expiration: str | None = None,
    max_responsibility_level: str = "R5",
) -> dict[str, Any]:
    """Build a synthetic envelope from scalar approved_scope (compat only)."""
    family = LEGACY_SCOPE_TO_FAMILY.get(approved_scope, "tool_permission")
    tools = list(allowed_tools) if allowed_tools is not None else []
    return {
        "envelope_version": ENVELOPE_VERSION,
        "capability_family": family,
        "operation": approved_scope or "unspecified",
        "target": None,
        "allowed_tools": tools,
        "cardinality": "single",
        "environment": None,
        "max_responsibility_level": max_responsibility_level,
        "constraints": {},
        "expiration": expiration,
        "legacy_approved_scope": approved_scope,
    }


def _responsibility_rank(level: str | None) -> int:
    if not level or not str(level).startswith("R"):
        return 99
    digits = "".join(ch for ch in str(level)[1:] if ch.isdigit())
    return int(digits) if digits else 99


def envelope_narrows(
    granted: dict[str, Any],
    requested: dict[str, Any],
) -> bool:
    """True when requested is a set-inclusion narrowing of granted (same family).

    Cross-family envelopes are incomparable (always False). Narrowing requires:
    same family; requested tools ⊆ granted tools; requested cardinality ≤ granted;
    requested responsibility ≤ granted; environment equal or granted unrestricted;
    requested expiration not after granted expiration when both set.
    """
    if granted.get("capability_family") != requested.get("capability_family"):
        return False  # cross-family grants are incomparable
    granted_tools = set(granted.get("allowed_tools") or [])
    requested_tools = set(requested.get("allowed_tools") or [])
    if not requested_tools.issubset(granted_tools):
        return False
    # Cardinality: unbounded covers bounded/single; bounded covers single.
    order = {"single": 0, "bounded": 1, "unbounded": 2}
    g_card = order.get(str(granted.get("cardinality") or "single"), 0)
    r_card = order.get(str(requested.get("cardinality") or "single"), 0)
    if r_card > g_card:
        return False
    if _responsibility_rank(requested.get("max_responsibility_level")) > _responsibility_rank(
        granted.get("max_responsibility_level")
    ):
        return False
    g_env = granted.get("environment")
    r_env = requested.get("environment")
    if g_env not in (None, "", "*") and r_env not in (None, "", "*") and g_env != r_env:
        return False
    if g_env not in (None, "", "*") and r_env in (None, "", "*"):
        # Requested unrestricted environment is broader than a granted pinned env.
        return False
    g_exp = granted.get("expiration")
    r_exp = requested.get("expiration")
    if g_exp and r_exp and str(r_exp) > str(g_exp):
        return False
    return True


def authorization_covers(
    *,
    granted_envelope: dict[str, Any] | None = None,
    requested_envelope: dict[str, Any] | None = None,
    granted_scope: str = "",
    requested_scope: str = "",
    scalar_covers: Any = None,
) -> tuple[bool, str]:
    """Primary authorization comparator: prefer envelopes; scalar is legacy only.

    Returns ``(covers, comparator)`` where comparator is ``envelope`` or
    ``legacy_scalar``.
    """
    if granted_envelope is not None and requested_envelope is not None:
        return envelope_narrows(granted_envelope, requested_envelope), "envelope"
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
    """Resolve envelope from grant or legacy scalar adapter.

    Raises GrantVerificationError when require_envelope and none present /
    legacy adapter disabled.
    """
    envelope = extract_capability_envelope(scope_grant)
    if envelope is not None:
        errors = validate_capability_envelope(envelope)
        if errors:
            raise GrantVerificationError("; ".join(errors), errors=errors)
        return envelope

    if require_envelope and not allow_legacy_adapter:
        raise GrantVerificationError(
            "capability_envelope required; scalar scope ranks are not sufficient "
            "(directive §3)",
            errors=["capability_envelope_missing"],
        )

    if not allow_legacy_adapter:
        raise GrantVerificationError(
            "capability_envelope missing and legacy scalar adapter disabled",
            errors=["capability_envelope_missing"],
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
    expires = scope_grant.get("expires_at") or auth.get("expires_at")
    return legacy_scope_to_envelope(
        approved_scope=approved,
        allowed_tools=tools,
        expiration=expires,
    )
