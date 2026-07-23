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
from akta.grant_override import (
    apply_grant_override_metadata,
    enrich_layer_satisfaction_from_evidence,
    strip_legacy_evidence_override,
)
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


def grant_scope_covers_action(
    granted_scope: str,
    requested_scope: str,
    *,
    allow_rank_fallback: bool = False,
) -> bool:
    """Return True when granted scope covers requested (legacy scalar path only).

    Production / pilot / release / cross_repo MUST use ``envelope_covers_request``.
    Rank comparison (``granted_rank >= requested_rank``) is deleted from production
    paths (P0-B). Enable ``allow_rank_fallback`` only for unit tests / migration.
    """
    if granted_scope == requested_scope:
        return True
    if is_valid_narrowing_grant(granted_scope=granted_scope, requested_scope=requested_scope):
        return True
    if not allow_rank_fallback:
        return False
    # Migration/unit only — never used by strict grant apply paths.
    return _scope_rank(granted_scope) >= _scope_rank(requested_scope)


def envelope_covers_request(
    granted_envelope: dict[str, Any],
    requested_envelope: dict[str, Any],
) -> bool:
    """Primary authorization comparator (directive §3): same-family set inclusion."""
    from akta.capability_envelope import authorization_covers

    covers, _ = authorization_covers(
        granted_envelope=granted_envelope,
        requested_envelope=requested_envelope,
    )
    return covers


def akta_cannot_broaden_grant(
    granted_scope: str,
    requested_upgrade_scope: str,
) -> bool:
    """AKTA must not upgrade e.g. protocol_draft grant into robot_queue_submission."""
    if requested_upgrade_scope not in VALID_REQUESTED_SCOPES:
        return True
    return not grant_scope_covers_action(granted_scope, requested_upgrade_scope)


def akta_cannot_broaden_envelope(
    granted_envelope: dict[str, Any],
    requested_envelope: dict[str, Any],
) -> bool:
    """True when AKTA must refuse to broaden beyond the granted envelope."""
    return not envelope_covers_request(granted_envelope, requested_envelope)


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
    """Invalidate grant when any bound consequential state changes (P0-E).

    Missing consequential context → renewed review (never infer missing == bound).
    """
    metadata = dict(context.get("metadata") or {})
    constraints = scope_grant.get("constraints") or {}
    expiration = scope_grant.get("expiration") or {}
    expires_after = list(expiration.get("expires_after") or [])
    if isinstance(expiration.get("expires_on"), str):
        expires_after.append(expiration["expires_on"])

    bound_evidence = metadata.get("bound_evidence_state") or constraints.get("evidence_state")
    bound_protocol = (
        metadata.get("bound_protocol_version") or constraints.get("protocol_version")
    )
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

    # Missing consequential bindings → abstain / renewed review.
    required_events = {
        "protocol_version_change": ("protocol_version", bound_protocol, current_protocol),
        "evidence_state_change": ("evidence_state", bound_evidence, current_evidence),
        "validation_status_change": (
            "validation_status",
            constraints.get("validation_status") or metadata.get("bound_validation_status"),
            context.get("validation_status") or metadata.get("validation_status"),
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
            context.get("model_version") or metadata.get("model_version"),
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
            context.get("domain_overlay") or metadata.get("domain_overlay_hash"),
        ),
        "safety_incident": (
            "safety_incident_state",
            constraints.get("safety_incident_state")
            or metadata.get("bound_safety_incident_state"),
            metadata.get("safety_incident_state"),
        ),
    }

    for event in expires_after:
        spec = required_events.get(str(event))
        if not spec:
            continue
        label, bound, current = spec
        if bound is None:
            return EvaluationLayer(
                source="review_loop",
                decision="review_required",
                reason=(
                    f"Missing consequential grant context {label!r} for expiration "
                    f"event {event!r}; abstain / renewed review (never infer missing == bound)."
                ),
            )
        if current is not None and str(bound) != str(current):
            return EvaluationLayer(
                source="review_loop",
                decision="review_required",
                reason=(
                    f"Grant bound state changed for {label} ({bound} -> {current}); "
                    "SCOPE grant requires renewed review."
                ),
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
    if not expires_at:
        abs_exp = expiration.get("absolute_expiration") if isinstance(expiration, dict) else None
        expires_at = abs_exp
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
    """Enforce grant allowed_tools when explicitly declared.

    Distinction (directive §2.2):
    - field absent → no allowlist enforcement here (verifier should reject
      runtime grants missing the field; see ``akta/scope_grant_verifier.py``)
    - allowed_tools=[] → deny all tools
    - allowed_tools=[...] → exact allowlist
    """
    if not metadata.get("prior_review_allowed_tools_explicit"):
        allowed = metadata.get("prior_review_allowed_tools")
        if not allowed:
            return None
    else:
        allowed = metadata.get("prior_review_allowed_tools") or []
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
    deployment_profile: str | None = None,
    verification_mode: str | None = None,
    require_capability_envelope: bool | None = None,
    trust_store: dict[str, Any] | None = None,
    ledger_status: dict[str, Any] | None = None,
) -> GrantLoopState:
    """Apply SCOPE grant to context and detect invalidation before re-gate.

    Grant verification runs inside ``apply_scope_grant_to_context`` before
    metadata is applied.
    """
    ctx_dict = context.to_dict() if isinstance(context, AKTAContext) else dict(context)
    ctx_dict = apply_scope_grant_to_context(
        ctx_dict,
        scope_grant,
        record=record,
        trigger=trigger,
        validate_grant=True,
        verification_mode=verification_mode,
        require_capability_envelope=require_capability_envelope,
        trust_store=trust_store,
        ledger_status=ledger_status,
    )

    bounds = _bound_values_from_record(record)
    metadata = dict(ctx_dict.get("metadata") or {})
    if bounds.get("bound_evidence_state"):
        metadata.setdefault("bound_evidence_state", bounds["bound_evidence_state"])
    if bounds.get("bound_protocol_version"):
        metadata.setdefault("bound_protocol_version", bounds["bound_protocol_version"])
    ctx_dict["metadata"] = metadata
    ctx_dict = enforce_grant_expiry(ctx_dict)

    profile = (
        deployment_profile
        or str(ctx_dict.get("deployment_profile") or "")
        or str((record or {}).get("deployment_profile") or "P2_analysis_assistant")
    )
    evidence_state = str(
        ctx_dict.get("evidence_state")
        or (record or {}).get("classification", {}).get("evidence_state")
        or ""
    )
    ctx_dict = apply_grant_override_metadata(
        ctx_dict,
        deployment_profile=profile,
        evidence_state=evidence_state,
        scope_grant=scope_grant,
    )
    # Defense in depth: never carry the removed evidence-layer override flag.
    metadata = strip_legacy_evidence_override(dict(ctx_dict.get("metadata") or {}))
    ctx_dict["metadata"] = metadata

    granted = _scope_grant_approved_scope(scope_grant) or ""
    requested = _scope_grant_requested_scope(scope_grant, record, trigger) or ""
    auth = scope_grant.get("authorization") or {}
    if "allowed_tools" in scope_grant:
        allowed = list(scope_grant.get("allowed_tools") or [])
    elif "allowed_tools" in auth:
        allowed = list(auth.get("allowed_tools") or [])
    elif metadata.get("prior_review_allowed_tools_explicit"):
        allowed = list(metadata.get("prior_review_allowed_tools") or [])
    else:
        allowed = []
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
    explicit_allowlist = bool(metadata.get("prior_review_allowed_tools_explicit"))
    grant_tools = grant_state.grant_allowed_tools
    if explicit_allowlist or grant_tools:
        # Empty explicit allowlist narrows to deny-all.
        grant_set = set(grant_tools)
        allowed = allowed & grant_set if grant_set else set()
        if requested_tool in grant_set:
            allowed.add(requested_tool)
        updated["allowed_tools"] = sorted(allowed)

    # Record evidence as unsatisfied when the composed decision is still blocked
    # by policy; grants never clear evidence-based blocks.
    adm = updated.get("admissibility", "")
    evidence_blocked = adm in ("blocked", "abstain_insufficient_context")
    enriched_ctx = enrich_layer_satisfaction_from_evidence(
        grant_state.context,
        evidence_decision=adm if evidence_blocked else None,
        evidence_reason=updated.get("decision_reason"),
    )
    satisfaction = (enriched_ctx.get("metadata") or {}).get("grant_layer_satisfaction")
    if satisfaction:
        # Mark review/authorization layers as satisfied when a grant was applied.
        # Never rewrite an evidence block into allowed.
        if evidence_blocked:
            for layer in satisfaction.get("satisfied_layers") or []:
                if layer.get("layer") == "evidence":
                    raise AssertionError(
                        "forbidden: evidence layer listed under satisfied_layers"
                    )
            updated["admissibility"] = adm  # explicit: grant cannot upgrade evidence block
            updated["review_required"] = updated.get("review_required", False)
            # Clear authorization_required / review_required only when evidence is not the block
            # (evidence block stays blocked).
        else:
            if adm in ("review_required", "authorization_required"):
                # Grant satisfied human review/auth; remaining review_required is from
                # other layers (profile/overlay) — keep as-is.
                pass
            updated["review_satisfied"] = True
            updated["authorization_satisfied"] = True
        updated["grant_layer_satisfaction"] = satisfaction
        envelope = metadata.get("capability_envelope")
        if envelope:
            updated["capability_envelope"] = envelope

    return updated
