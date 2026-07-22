"""Review decision import, expiry enforcement, and scoped re-gate (v0.6)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from akta.records import validate_against_schema
from akta.scope_contract import (
    _scope_grant_approved_scope,
    _scope_grant_requested_scope,
    validate_approval_grant,
)


def load_review_decision(path: str | Path, *, validate: bool = True) -> dict[str, Any]:
    """Load and optionally validate a SCOPE review decision artifact."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if validate:
        validate_against_schema(data, "review_decision.schema.json")
    return data


def load_scope_grant(path: str | Path) -> dict[str, Any]:
    """Load a SCOPE grant artifact (JSON)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _parse_iso8601(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def is_review_expired(expires_at: str | None, *, now: datetime | None = None) -> bool:
    """Return True when expires_at is in the past (F14)."""
    if not expires_at:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        expiry = _parse_iso8601(expires_at)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return expiry <= now
    except ValueError:
        return True


def review_decision_to_context_metadata(review_decision: dict[str, Any]) -> dict[str, Any]:
    """Map review decision fields into AKTA context metadata."""
    expires_at = review_decision.get("expires_at")
    expired = is_review_expired(expires_at)
    metadata: dict[str, Any] = {
        "prior_review_id": review_decision.get("review_decision_id"),
        "prior_review_scope": review_decision.get("granted_scope"),
        "prior_review_decision": review_decision.get("decision"),
        "prior_review_expired": expired,
        "prior_review_reviewer": review_decision.get("reviewer_id"),
    }
    if expires_at:
        metadata["prior_review_expires_at"] = expires_at
    if review_decision.get("review_trigger_id"):
        metadata["prior_review_trigger_id"] = review_decision["review_trigger_id"]
    return metadata


def scope_grant_to_context_metadata(
    scope_grant: dict[str, Any],
    *,
    record: dict[str, Any] | None = None,
    trigger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map SCOPE grant into AKTA context metadata for scoped re-gate."""
    granted = _scope_grant_approved_scope(scope_grant) or ""
    requested = _scope_grant_requested_scope(scope_grant, record, trigger) or ""
    expires_at = (
        scope_grant.get("expires_at")
        or (scope_grant.get("authorization") or {}).get("expires_at")
    )
    grant_id = scope_grant.get("grant_id") or scope_grant.get("scope_grant_id")
    metadata: dict[str, Any] = {
        "prior_review_id": grant_id,
        "prior_review_grant_id": grant_id,
        "prior_review_scope": granted,
        "prior_review_decision": "approved",
        "prior_review_expired": is_review_expired(expires_at),
        "prior_review_requested_scope": requested,
    }
    if expires_at:
        metadata["prior_review_expires_at"] = expires_at
    auth = scope_grant.get("authorization") or {}
    if "allowed_tools" in scope_grant:
        metadata["prior_review_allowed_tools"] = list(scope_grant.get("allowed_tools") or [])
        metadata["prior_review_allowed_tools_explicit"] = True
    elif "allowed_tools" in auth:
        metadata["prior_review_allowed_tools"] = list(auth.get("allowed_tools") or [])
        metadata["prior_review_allowed_tools_explicit"] = True
    blocked = scope_grant.get("blocked_tools") or auth.get("blocked_tools")
    if blocked:
        metadata["prior_review_blocked_tools"] = list(blocked)
    provenance = scope_grant.get("provenance")
    if provenance:
        metadata["prior_review_provenance"] = dict(provenance)
    return metadata


def apply_review_decision_to_context(
    context: dict[str, Any],
    review_decision: dict[str, Any],
) -> dict[str, Any]:
    """Map an imported review decision into AKTA context metadata."""
    context = dict(context)
    metadata = dict(context.get("metadata") or {})
    metadata.update(review_decision_to_context_metadata(review_decision))
    context["metadata"] = metadata
    return context


def apply_scope_grant_to_context(
    context: dict[str, Any],
    scope_grant: dict[str, Any],
    *,
    record: dict[str, Any] | None = None,
    trigger: dict[str, Any] | None = None,
    validate_grant: bool = True,
    verification_mode: str | None = None,
    require_capability_envelope: bool | None = None,
) -> dict[str, Any]:
    """Apply SCOPE grant metadata to context after optional grant verification.

    When ``validate_grant`` is True, runs ``verify_scope_grant_or_raise`` BEFORE
    any metadata is applied (directive §4).
    """
    verification: dict[str, Any] | None = None
    granted = _scope_grant_approved_scope(scope_grant) or ""
    requested = _scope_grant_requested_scope(scope_grant, record, trigger) or ""
    if validate_grant:
        from akta.scope_grant_verifier import verify_scope_grant_or_raise

        result = verify_scope_grant_or_raise(
            scope_grant,
            mode=verification_mode,
            require_capability_envelope=require_capability_envelope,
            record=record,
            trigger=trigger,
        )
        verification = {
            "ok": result.ok,
            "mode": result.mode,
            "warnings": list(result.warnings),
            "checks_run": list(result.checks_run),
        }
        if granted and requested:
            validate_approval_grant(granted_scope=granted, requested_scope=requested)

    context = dict(context)
    metadata = dict(context.get("metadata") or {})
    metadata.update(scope_grant_to_context_metadata(scope_grant, record=record, trigger=trigger))
    if verification is not None:
        metadata["grant_verification"] = verification
    # Attach resolved capability envelope. Explicit envelopes are the primary
    # authorization comparator; scalar approved_scope is a deprecated adapter.
    from akta.capability_envelope import (
        extract_capability_envelope,
        legacy_scope_to_envelope,
        resolve_grant_envelope,
    )

    envelope = resolve_grant_envelope(
        scope_grant,
        require_envelope=False,
        allow_legacy_adapter=True,
    )
    metadata["capability_envelope"] = envelope
    auth = scope_grant.get("authorization") or {}
    raw_envelope = extract_capability_envelope(scope_grant)
    metadata["authorization_comparator"] = (
        "envelope" if raw_envelope is not None else "legacy_scalar"
    )
    if metadata["authorization_comparator"] == "legacy_scalar":
        metadata["authorization_comparator_deprecated"] = True
    if granted and requested and raw_envelope is not None:
        # Prefer envelope inclusion over scalar ranks when both sides resolve.
        requested_envelope = legacy_scope_to_envelope(
            approved_scope=requested,
            allowed_tools=list(envelope.get("allowed_tools") or []),
            max_responsibility_level=str(
                envelope.get("max_responsibility_level") or "R5"
            ),
        )
        from akta.capability_envelope import authorization_covers

        covers, comparator = authorization_covers(
            granted_envelope=envelope,
            requested_envelope=requested_envelope,
            granted_scope=granted,
            requested_scope=requested,
        )
        metadata["envelope_covers_requested_scope"] = covers
        metadata["authorization_comparator"] = comparator
    tools_explicit = (
        "allowed_tools" in scope_grant
        or "allowed_tools" in auth
        or (isinstance(raw_envelope, dict) and "allowed_tools" in raw_envelope)
    )
    if tools_explicit:
        metadata["prior_review_allowed_tools"] = list(envelope.get("allowed_tools") or [])
        metadata["prior_review_allowed_tools_explicit"] = True
    context["metadata"] = metadata
    return context


def enforce_grant_expiry(
    context: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh prior_review_expired flag from expires_at (F14)."""
    context = dict(context)
    metadata = dict(context.get("metadata") or {})
    expires_at = metadata.get("prior_review_expires_at")
    if expires_at:
        metadata["prior_review_expired"] = is_review_expired(expires_at, now=now)
    context["metadata"] = metadata
    return context


def process_review_loop(
    gate: Any,
    *,
    ai_output: Any,
    requested_tool: str,
    requested_action: str,
    context: dict[str, Any],
    deployment_profile: str = "P2_analysis_assistant",
    domain_overlay: str | None = None,
    scope_grant: dict[str, Any] | None = None,
    review_decision: dict[str, Any] | None = None,
    record: dict[str, Any] | None = None,
    trigger: dict[str, Any] | None = None,
) -> Any:
    """Full closed-loop: apply grant/decision, enforce expiry, scoped re-gate."""
    from akta.context import AKTAContext

    ctx = dict(context)
    if review_decision is not None:
        ctx = apply_review_decision_to_context(ctx, review_decision)
    elif scope_grant is not None:
        ctx = apply_scope_grant_to_context(
            ctx, scope_grant, record=record, trigger=trigger, validate_grant=True
        )

    ctx = enforce_grant_expiry(ctx)

    metadata = ctx.get("metadata") or {}
    if metadata.get("prior_review_expired") and metadata.get("prior_review_id"):
        return gate.evaluate(
            ai_output=ai_output,
            requested_tool=requested_tool,
            requested_action=requested_action,
            context=AKTAContext.from_dict(ctx),
            deployment_profile=deployment_profile,
            domain_overlay=domain_overlay,
        )

    if hasattr(gate, "evaluate_with_grant"):
        return gate.evaluate_with_grant(
            ai_output=ai_output,
            requested_tool=requested_tool,
            requested_action=requested_action,
            context=AKTAContext.from_dict(ctx),
            deployment_profile=deployment_profile,
            domain_overlay=domain_overlay,
            scope_grant=scope_grant,
            review_decision=review_decision,
        )

    return gate.evaluate(
        ai_output=ai_output,
        requested_tool=requested_tool,
        requested_action=requested_action,
        context=AKTAContext.from_dict(ctx),
        deployment_profile=deployment_profile,
        domain_overlay=domain_overlay,
    )
