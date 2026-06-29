"""Closed-loop review semantics — AKTA x SCOPE grant re-gate (v0.7).

AKTA evaluates the requested action, SCOPE grants scoped authorization, and AKTA
re-gates follow-up actions against that grant. AKTA never broadens a SCOPE grant;
it may only narrow scope, block, or require renewed review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from akta.context import AKTAContext
from akta.evaluation_types import EvaluationLayer
from akta.review_decision import (
    apply_scope_grant_to_context,
    enforce_grant_expiry,
    is_review_expired,
)
from akta.scope_contract import (
    _scope_grant_approved_scope,
    _scope_grant_requested_scope,
    is_valid_narrowing_grant,
    scope_rank,
)
from akta.scope_mapping import VALID_REQUESTED_SCOPES

SCOPE_RANK_ORDER: dict[str, int] = {
    scope: scope_rank(scope)
    for scope in (
        "protocol_draft",
        "active_protocol_update",
        "single_validation_plan",
        "single_validation_run_draft",
        "single_run_queue_priority",
        "robot_queue_submission",
        "execution_payload_preparation",
        "publication_claim",
        "scientific_memory_import",
        "draft_only",
    )
}


def _scope_rank(scope: str) -> int:
    try:
        return scope_rank(scope)
    except FileNotFoundError:
        return SCOPE_RANK_ORDER.get(scope, 99)


def _evidence_rank(evidence_state: str) -> int:
    if evidence_state.startswith("E") and len(evidence_state) > 1 and evidence_state[1].isdigit():
        return int(evidence_state[1])
    return 0


def grant_scope_covers_action(granted_scope: str, requested_scope: str) -> bool:
    """Return True when granted scope covers the requested scope (narrow grants only)."""
    if granted_scope == requested_scope:
        return True
    if is_valid_narrowing_grant(granted_scope=granted_scope, requested_scope=requested_scope):
        return True
    return _scope_rank(granted_scope) >= _scope_rank(requested_scope)


def akta_cannot_broaden_grant(
    granted_scope: str,
    requested_upgrade_scope: str,
) -> bool:
    """AKTA must not upgrade e.g. protocol_draft grant into robot_queue_submission."""
    if requested_upgrade_scope not in VALID_REQUESTED_SCOPES:
        return True
    return not grant_scope_covers_action(granted_scope, requested_upgrade_scope)


@dataclass
class GrantLoopState:
    """Prepared context and enforcement metadata for grant re-gate."""

    context: dict[str, Any]
    granted_scope: str = ""
    requested_scope: str = ""
    grant_allowed_tools: list[str] = field(default_factory=list)
    trigger_blocked_tools: list[str] = field(default_factory=list)
    grant_invalidated: bool = False
    grant_invalid_reason: str | None = None


def _bound_values_from_record(record: dict[str, Any] | None) -> dict[str, Any]:
    if not record:
        return {}
    classification = record.get("classification") or {}
    scientific = record.get("scientific_context") or {}
    return {
        "bound_evidence_state": classification.get("evidence_state"),
        "bound_protocol_version": scientific.get("protocol_version") or scientific.get("active_protocol_id"),
    }


def check_grant_context_validity(
    context: dict[str, Any],
    *,
    scope_grant: dict[str, Any],
    record: dict[str, Any] | None = None,
) -> EvaluationLayer | None:
    """Invalidate grant when protocol or evidence context downgrades vs grant binding."""
    metadata = dict(context.get("metadata") or {})
    bound_evidence = metadata.get("bound_evidence_state")
    bound_protocol = metadata.get("bound_protocol_version")

    if bound_evidence is None or bound_protocol is None:
        bounds = _bound_values_from_record(record)
        bound_evidence = bound_evidence or bounds.get("bound_evidence_state")
        bound_protocol = bound_protocol or bounds.get("bound_protocol_version")

    current_evidence = context.get("evidence_state")
    current_protocol = (
        context.get("protocol_version")
        or context.get("active_protocol_id")
        or (context.get("scientific_context") or {}).get("protocol_version")
    )

    if bound_evidence and current_evidence:
        if _evidence_rank(current_evidence) < _evidence_rank(str(bound_evidence)):
            return EvaluationLayer(
                source="review_loop",
                decision="review_required",
                reason=(
                    f"Evidence downgraded from {bound_evidence} to {current_evidence}; "
                    "SCOPE grant requires renewed review."
                ),
            )

    if bound_protocol and current_protocol and str(bound_protocol) != str(current_protocol):
        return EvaluationLayer(
            source="review_loop",
            decision="review_required",
            reason=(
                f"Protocol context changed ({bound_protocol} -> {current_protocol}); "
                "SCOPE grant requires renewed review."
            ),
        )

    expires_at = metadata.get("prior_review_expires_at")
    if expires_at and is_review_expired(expires_at):
        return EvaluationLayer(
            source="review_loop",
            decision="review_required",
            reason="SCOPE grant expired; renewed review required.",
        )

    return None


def evaluate_grant_tool_allowlist(
    metadata: dict[str, Any],
    requested_tool: str,
) -> EvaluationLayer | None:
    """Enforce grant allowed_tools when present."""
    allowed = metadata.get("prior_review_allowed_tools")
    if not allowed:
        return None
    allowed_set = set(allowed)
    if requested_tool not in allowed_set:
        return EvaluationLayer(
            source="review_loop",
            decision="blocked",
            reason=(
                f"Tool {requested_tool} not in SCOPE grant allowed_tools: "
                f"{sorted(allowed_set)}."
            ),
        )
    return None


def prepare_grant_context(
    context: dict[str, Any] | AKTAContext,
    *,
    scope_grant: dict[str, Any],
    record: dict[str, Any] | None = None,
    trigger: dict[str, Any] | None = None,
) -> GrantLoopState:
    """Apply SCOPE grant to context and detect invalidation before re-gate."""
    ctx_dict = context.to_dict() if isinstance(context, AKTAContext) else dict(context)
    ctx_dict = apply_scope_grant_to_context(
        ctx_dict,
        scope_grant,
        record=record,
        trigger=trigger,
        validate_grant=True,
    )

    bounds = _bound_values_from_record(record)
    metadata = dict(ctx_dict.get("metadata") or {})
    if bounds.get("bound_evidence_state"):
        metadata.setdefault("bound_evidence_state", bounds["bound_evidence_state"])
    if bounds.get("bound_protocol_version"):
        metadata.setdefault("bound_protocol_version", bounds["bound_protocol_version"])
    ctx_dict["metadata"] = metadata
    ctx_dict = enforce_grant_expiry(ctx_dict)

    granted = _scope_grant_approved_scope(scope_grant) or ""
    requested = _scope_grant_requested_scope(scope_grant, record, trigger) or ""
    allowed = scope_grant.get("allowed_tools") or (
        (scope_grant.get("authorization") or {}).get("allowed_tools") or []
    )
    trigger_blocked = list((trigger or {}).get("blocked_tools") or [])

    invalidation = check_grant_context_validity(
        ctx_dict,
        scope_grant=scope_grant,
        record=record,
    )

    state = GrantLoopState(
        context=ctx_dict,
        granted_scope=granted,
        requested_scope=requested,
        grant_allowed_tools=list(allowed),
        trigger_blocked_tools=trigger_blocked,
        grant_invalidated=invalidation is not None,
        grant_invalid_reason=invalidation.reason if invalidation else None,
    )
    return state


def apply_grant_decision_constraints(
    decision_data: dict[str, Any],
    grant_state: GrantLoopState,
    *,
    requested_tool: str,
) -> dict[str, Any]:
    """Merge SCOPE blocked_tools and grant allowlist into final decision."""
    updated = dict(decision_data)
    blocked = set(updated.get("blocked_tools") or [])
    blocked.update(grant_state.trigger_blocked_tools)

    metadata = grant_state.context.get("metadata") or {}
    blocked.update(metadata.get("prior_review_blocked_tools") or [])
    tool_layer = evaluate_grant_tool_allowlist(metadata, requested_tool)
    if tool_layer:
        blocked.add(requested_tool)
        adm = updated.get("admissibility", "")
        if adm in ("allowed", "allowed_with_logging", "draft_only"):
            updated["admissibility"] = tool_layer.decision
            updated["decision_reason"] = tool_layer.reason

    if grant_state.grant_invalidated:
        adm = updated.get("admissibility", "")
        if adm in ("allowed", "allowed_with_logging", "draft_only"):
            updated["admissibility"] = "review_required"
            updated["review_required"] = True
            updated["decision_reason"] = grant_state.grant_invalid_reason or (
                "SCOPE grant invalidated; renewed review required."
            )

    updated["blocked_tools"] = sorted(blocked)

    allowed = set(updated.get("allowed_tools") or [])
    if grant_state.grant_allowed_tools:
        allowed = allowed & set(grant_state.grant_allowed_tools)
        if requested_tool in grant_state.grant_allowed_tools:
            allowed.add(requested_tool)
        updated["allowed_tools"] = sorted(allowed)

    return updated
