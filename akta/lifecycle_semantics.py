"""Lifecycle context semantics (AKTA 1.1 WS10).

Signed grant status is authoritative for remaining uses, revocation,
supersession, reviewer withdrawal, and SCOPE expiration events.
AKTA context remains authoritative for scientific/protocol/evidence/
validation/model/tool-registry/policy/overlay/safety state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from akta.evaluation_types import EvaluationLayer

# Events whose truth comes from signed status / SCOPE ledger — never caller metadata.
STATUS_AUTHORITATIVE_EVENTS = frozenset(
    {
        "grant_revoked",
        "grant_consumed",
        "grant_superseded",
        "reviewer_withdrawal",
        "scope_expiration",
        "cardinality_exhausted",
        "single_use_consumed",
    }
)

# Events compared against AKTA scientific / deployment context.
AKTA_CONTEXT_EVENTS = frozenset(
    {
        "protocol_version_change",
        "evidence_state_change",
        "validation_status_change",
        "policy_version_change",
        "model_version_change",
        "tool_registry_change",
        "domain_overlay_change",
        "safety_incident",
    }
)

EVIDENCE_RANK_PREFIX = "E"


def _parse_iso(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _evidence_rank(value: Any) -> int | None:
    text = str(value or "")
    if text.startswith(EVIDENCE_RANK_PREFIX) and len(text) > 1 and text[1].isdigit():
        digits = ""
        for ch in text[1:]:
            if ch.isdigit():
                digits += ch
            else:
                break
        return int(digits) if digits else None
    return None


def compare_exact(bound: Any, current: Any) -> bool:
    """True when bound and current are present and equal as strings."""
    if bound is None or current is None:
        return False
    return str(bound) == str(current)


def compare_evidence_rank_non_decreasing(bound: Any, current: Any) -> bool:
    """Evidence may stay or improve; downgrade invalidates the grant."""
    b = _evidence_rank(bound)
    c = _evidence_rank(current)
    if b is None or c is None:
        return compare_exact(bound, current)
    return c >= b


def compare_hash_identity(bound: Any, current: Any) -> bool:
    return compare_exact(bound, current)


def compare_safety_incident(bound: Any, current: Any) -> bool:
    """Any new safety incident relative to bound 'clear' state invalidates."""
    if bound is None or current is None:
        return False
    bound_s = str(bound).lower()
    current_s = str(current).lower()
    if bound_s in {"clear", "none", "ok", "false", "0"}:
        return current_s in {"clear", "none", "ok", "false", "0"}
    return bound_s == current_s


EXPIRES_AFTER_COMPARATORS: dict[str, Callable[[Any, Any], bool]] = {
    "protocol_version_change": compare_exact,
    "evidence_state_change": compare_evidence_rank_non_decreasing,
    "validation_status_change": compare_exact,
    "policy_version_change": compare_hash_identity,
    "model_version_change": compare_exact,
    "tool_registry_change": compare_hash_identity,
    "domain_overlay_change": compare_hash_identity,
    "safety_incident": compare_safety_incident,
}


@dataclass
class LifecycleCheckResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    renewed_review_required: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_evaluation_layer(self) -> EvaluationLayer | None:
        if self.ok:
            return None
        reason = "; ".join(self.reasons or self.errors) or "grant lifecycle invalid"
        return EvaluationLayer(
            source="lifecycle_semantics",
            decision="review_required",
            reason=reason,
        )


def extract_status_lifecycle(ledger_status: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize status-authoritative lifecycle fields."""
    if not ledger_status:
        return {}
    remaining = ledger_status.get("cardinality_remaining")
    if remaining is None:
        remaining = ledger_status.get("single_use_remaining")
    return {
        "status": ledger_status.get("status"),
        "cardinality_remaining": remaining,
        "uses_consumed": ledger_status.get("uses_consumed"),
        "revoked": ledger_status.get("revoked") is True
        or str(ledger_status.get("status") or "") == "revoked",
        "superseded": str(ledger_status.get("status") or "") == "superseded",
        "reviewer_withdrawal": bool(
            ledger_status.get("reviewer_withdrawal")
            or ledger_status.get("withdrawn_by_reviewer")
        ),
        "scope_expires_at": ledger_status.get("scope_expires_at")
        or ledger_status.get("expires_at"),
        "revocation_reason": ledger_status.get("revocation_reason"),
        "ledger_sequence": ledger_status.get("ledger_sequence")
        or ledger_status.get("sequence"),
    }


def status_lifecycle_errors(
    ledger_status: dict[str, Any] | None,
    *,
    prefer_status_over_context: bool = True,
    context_metadata: dict[str, Any] | None = None,
) -> list[str]:
    """Errors from status-authoritative lifecycle fields.

    When status is present, caller metadata such as ``grant_use_count`` is ignored
    for remaining-use / revocation / supersession / withdrawal decisions.
    """
    errors: list[str] = []
    life = extract_status_lifecycle(ledger_status)
    if not life:
        return errors

    status = str(life.get("status") or "")
    if status in {
        "revoked",
        "consumed",
        "expired",
        "superseded",
        "invalid",
        "not_found",
        "used",
    }:
        errors.append(f"status-authoritative lifecycle status={status}")
    if life.get("revoked"):
        errors.append("grant revoked per signed status")
    if life.get("superseded"):
        errors.append("grant superseded per signed status")
    if life.get("reviewer_withdrawal"):
        errors.append("grant withdrawn by reviewer per signed status")

    remaining = life.get("cardinality_remaining")
    if remaining is not None and int(remaining) <= 0:
        errors.append("no remaining uses per signed status")

    scope_exp = life.get("scope_expires_at")
    if scope_exp:
        exp_dt = _parse_iso(scope_exp)
        if exp_dt is not None and exp_dt <= datetime.now(timezone.utc):
            errors.append(f"SCOPE expiration reached per signed status ({scope_exp})")

    if prefer_status_over_context and context_metadata:
        # Explicitly do not trust caller grant_use_count when status speaks.
        _ = context_metadata.get("grant_use_count")
    return errors


def resolve_bound_and_current(
    event: str,
    *,
    scope_grant: dict[str, Any],
    context: dict[str, Any] | None,
) -> tuple[str, Any, Any]:
    """Return (label, bound_value, current_value) for an expires_after event."""
    constraints = scope_grant.get("constraints") or {}
    ctx = context or {}
    metadata = dict(ctx.get("metadata") or {})

    mapping = {
        "protocol_version_change": (
            "protocol_version",
            constraints.get("protocol_version")
            or metadata.get("bound_protocol_version"),
            ctx.get("protocol_version")
            or ctx.get("active_protocol_id")
            or (ctx.get("scientific_context") or {}).get("protocol_version"),
        ),
        "evidence_state_change": (
            "evidence_state",
            constraints.get("evidence_state") or metadata.get("bound_evidence_state"),
            ctx.get("evidence_state"),
        ),
        "validation_status_change": (
            "validation_status",
            constraints.get("validation_status")
            or metadata.get("bound_validation_status"),
            ctx.get("validation_status") or metadata.get("validation_status"),
        ),
        "policy_version_change": (
            "policy_manifest_hash",
            constraints.get("policy_manifest_hash")
            or metadata.get("bound_policy_manifest_hash"),
            metadata.get("policy_manifest_hash"),
        ),
        "model_version_change": (
            "model_version",
            constraints.get("model_version") or metadata.get("bound_model_version"),
            ctx.get("model_version") or metadata.get("model_version"),
        ),
        "tool_registry_change": (
            "tool_registry_hash",
            constraints.get("tool_registry_hash")
            or constraints.get("tool_registry_version")
            or metadata.get("bound_tool_registry_hash"),
            metadata.get("tool_registry_hash"),
        ),
        "domain_overlay_change": (
            "domain_overlay_hash",
            constraints.get("domain_overlay")
            or constraints.get("domain_overlay_hash")
            or metadata.get("bound_domain_overlay_hash"),
            ctx.get("domain_overlay") or metadata.get("domain_overlay_hash"),
        ),
        "safety_incident": (
            "safety_incident_state",
            constraints.get("safety_incident_state")
            or metadata.get("bound_safety_incident_state"),
            metadata.get("safety_incident_state"),
        ),
    }
    return mapping.get(str(event), (str(event), None, None))


def check_expires_after_bindings(
    scope_grant: dict[str, Any],
    *,
    context: dict[str, Any] | None,
    ledger_status: dict[str, Any] | None = None,
) -> LifecycleCheckResult:
    """Evaluate every expires_after event with typed comparators.

    Missing bound or current value → renewed review / abstain (never infer equality).
    Status-authoritative events are evaluated from signed status only.
    """
    errors: list[str] = []
    reasons: list[str] = []
    renewed = False

    expiration = scope_grant.get("expiration") or {}
    expires_after = list(expiration.get("expires_after") or [])
    if isinstance(expiration.get("expires_on"), str):
        expires_after.append(expiration["expires_on"])

    # Status-authoritative lifecycle first.
    status_errs = status_lifecycle_errors(
        ledger_status,
        prefer_status_over_context=True,
        context_metadata=dict((context or {}).get("metadata") or {}),
    )
    errors.extend(status_errs)
    reasons.extend(status_errs)

    for event in expires_after:
        event_s = str(event)
        if event_s in STATUS_AUTHORITATIVE_EVENTS:
            # Already covered by status_lifecycle_errors when status present.
            if ledger_status is None:
                renewed = True
                msg = (
                    f"missing signed status for status-authoritative event {event_s!r}; "
                    "renewed review required"
                )
                errors.append(msg)
                reasons.append(msg)
            continue

        if event_s not in AKTA_CONTEXT_EVENTS and event_s not in EXPIRES_AFTER_COMPARATORS:
            continue

        label, bound, current = resolve_bound_and_current(
            event_s, scope_grant=scope_grant, context=context
        )
        if bound is None or current is None:
            renewed = True
            msg = (
                f"missing consequential grant context {label!r} for expiration "
                f"event {event_s!r}; abstain / renewed review required "
                "(never infer missing == bound)"
            )
            errors.append(msg)
            reasons.append(msg)
            continue

        comparator = EXPIRES_AFTER_COMPARATORS.get(event_s, compare_exact)
        if not comparator(bound, current):
            renewed = True
            msg = (
                f"Grant bound state changed for {label} ({bound} -> {current}); "
                "SCOPE grant requires renewed review."
            )
            errors.append(msg)
            reasons.append(msg)

    return LifecycleCheckResult(
        ok=not errors,
        errors=errors,
        renewed_review_required=renewed or bool(errors),
        reasons=reasons,
    )
