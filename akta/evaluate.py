"""Admissibility evaluation engine."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from akta.classify import action_rank, responsibility_rank
from akta.consequentiality import ConsequentialityResult, classify_consequentiality
from akta.context import AKTAContext
from akta.overlays import DomainOverlay
from akta.policy import PolicyBundle
from akta.review_context import (
    evaluate_disclaimer_boundary,
    evaluate_prior_akta_records,
    evaluate_prior_review,
)
from akta.tool_registry import ToolSpec


logger = logging.getLogger(__name__)


DECISION_ORDER = {
    "allowed": 0,
    "allowed_with_logging": 1,
    "draft_only": 2,
    "review_required": 3,
    "authorization_required": 4,
    "blocked": 5,
    "abstain_insufficient_context": 6,
}

VALIDATION_DRAFT_TOOLS = frozenset({
    "experiment_planner.create_validation_draft",
})

PERMISSION_TO_DECISION = {
    "allowed": "allowed",
    "allowed_with_logging": "allowed_with_logging",
    "draft_only": "draft_only",
    "review_required": "review_required",
    "authorization_required": "authorization_required",
    "blocked": "blocked",
    "abstain_insufficient_context": "abstain_insufficient_context",
}


from akta.evaluation_types import EvaluationLayer, EvaluationResult


def strictest(*decisions: str) -> str:
    if not decisions:
        return "blocked"
    return max(decisions, key=lambda d: DECISION_ORDER.get(d, 99))


def resolve_conditional_decision(
    policy: PolicyBundle,
    raw: str,
    profile: str,
    action_type: str,
    tool_spec: ToolSpec,
    requested_tool: str,
    consequentiality: ConsequentialityResult,
) -> str:
    """Resolve profile/evidence conditional decision tokens."""
    if raw in ("allowed", "allowed_with_logging", "draft_only", "review_required",
               "authorization_required", "blocked", "abstain_insufficient_context"):
        return policy.normalize_decision(raw)

    if raw in ("allowed_log_or_review", "allowed_log_nonconseq"):
        if raw == "allowed_log_nonconseq":
            return (
                "review_required" if consequentiality.consequential else "allowed_with_logging"
            )
        return "review_required" if consequentiality.consequential else "allowed_with_logging"

    if raw in ("draft_only_or_review_required", "draft_only_or_review"):
        profile_raw = policy.profile_matrix_raw(profile, action_type)
        candidates: list[str] = []
        for token in (raw, profile_raw):
            norm = policy.normalize_decision(token)
            if norm in ("draft_only", "review_required"):
                candidates.append(norm)
            elif token in ("draft_only_or_review_required", "draft_only_or_review"):
                if tool_spec.mutates_state or tool_spec.external_effect or "active" in requested_tool:
                    candidates.append("review_required")
                else:
                    candidates.append("draft_only")
        if not candidates:
            candidates.append("review_required")
        return strictest(*candidates)

    if raw == "draft_validation_only":
        if requested_tool in VALIDATION_DRAFT_TOOLS or "validation_draft" in requested_tool:
            return "draft_only"
        if tool_spec.default_permission == "draft_only" and not tool_spec.mutates_state:
            return "draft_only"
        return "blocked"

    if raw == "blocked_or_review":
        return "review_required"

    return policy.normalize_decision(raw)


def profile_decision(
    policy: PolicyBundle,
    profile: str,
    action_type: str,
    tool_spec: ToolSpec,
    requested_tool: str,
    consequentiality: ConsequentialityResult,
) -> str:
    raw = policy.profile_matrix_raw(profile, action_type)
    return resolve_conditional_decision(
        policy, raw, profile, action_type, tool_spec, requested_tool, consequentiality
    )


def evidence_decision(
    policy: PolicyBundle,
    evidence_state: str,
    action_type: str,
    profile: str,
    tool_spec: ToolSpec,
    requested_tool: str,
    consequentiality: ConsequentialityResult,
) -> tuple[str | None, str]:
    """Per-action evidence constraint lookup (v0.2)."""
    rules = policy.evidence_to_action_rules.get("rules", {})
    state_rules = rules.get(evidence_state)
    if not state_rules:
        return _legacy_evidence_decision(
            policy, evidence_state, action_type, tool_spec, consequentiality
        )

    raw = state_rules.get(action_type)
    if raw is None:
        return None, ""

    decision = resolve_conditional_decision(
        policy, raw, profile, action_type, tool_spec, requested_tool, consequentiality
    )
    return decision, (
        f"Evidence rule {evidence_state}+{action_type} constrains to {decision} "
        f"(resolved from {raw})."
    )


def _legacy_evidence_decision(
    policy: PolicyBundle,
    evidence_state: str,
    action_type: str,
    tool_spec: ToolSpec,
    consequentiality: ConsequentialityResult,
) -> tuple[str | None, str]:
    """Fallback to legacy rank-based matrix; fail-closed for consequential actions."""
    constraints = policy.evidence_to_action_matrix.get("constraints", {})
    constraint = constraints.get(evidence_state)
    if not constraint:
        if consequentiality.consequential or tool_spec.mutates_state:
            logger.warning(
                "No evidence rules for %s; fail-closed block for consequential action %s",
                evidence_state,
                action_type,
            )
            return "blocked", (
                f"No evidence rules for {evidence_state}; fail-closed block for "
                f"consequential action {action_type}."
            )
        return None, ""

    max_action = constraint.get("max_action", "A2_hypothesis_generation")
    max_rank = action_rank(max_action)
    current_rank = action_rank(action_type)

    if current_rank <= max_rank:
        mode = constraint.get("max_action_mode")
        if mode and current_rank == max_rank:
            return mode, (
                f"Evidence {evidence_state} limits action {action_type} to {mode} at maximum allowed rank."
            )
        return None, ""

    violation = constraint.get("violation_decision", "blocked")
    return violation, (
        f"Evidence {evidence_state} max action without review is {max_action}; "
        f"requested {action_type} exceeds limit."
    )


def overlay_decision(
    overlay: DomainOverlay | None,
    action_type: str,
    evidence_state: str,
    requested_tool: str,
) -> list[EvaluationLayer]:
    layers: list[EvaluationLayer] = []
    if overlay is None:
        return layers

    if action_type in overlay.blocked_actions():
        layers.append(
            EvaluationLayer(
                source="domain_overlay",
                decision="blocked",
                reason=f"Domain overlay {overlay.name} blocks action type {action_type}.",
            )
        )

    min_evidence = overlay.minimum_evidence_for()
    action_key_map = {
        "A4_recommendation": "recommendation",
        "A5_protocol_modification": "protocol_modification",
        "A6_experimental_planning": "experimental_planning",
        "A7_resource_or_queue_prioritization": "queue_prioritization",
        "A8_tool_or_workflow_mutation": "tool_or_workflow_mutation",
        "A9_execution_adjacent_or_external_action": "execution_adjacent",
        "A10_publication_or_claim_escalation": "publication_claim",
    }
    key = action_key_map.get(action_type)
    if key and key in min_evidence:
        required = min_evidence[key]
        req_rank = _evidence_rank(required)
        cur_rank = _evidence_rank(evidence_state)
        if cur_rank < req_rank:
            layers.append(
                EvaluationLayer(
                    source="domain_overlay",
                    decision="blocked",
                    reason=(
                        f"Domain overlay requires {required} for {key}; "
                        f"current evidence is {evidence_state}."
                    ),
                )
            )

    for tool, restriction in overlay.tool_restrictions().items():
        if tool == requested_tool and "decision" in restriction:
            layers.append(
                EvaluationLayer(
                    source="domain_overlay_tool",
                    decision=restriction["decision"],
                    reason=f"Domain overlay restricts tool {tool} to {restriction['decision']}.",
                )
            )

    return layers


def hazard_trigger_decision(
    overlay: DomainOverlay | None,
    context: AKTAContext,
) -> EvaluationLayer | None:
    """Apply domain hazard triggers from overlay metadata/context."""
    if overlay is None:
        return None

    triggers = overlay.data.get("hazard_triggers", [])
    if not triggers:
        return None

    metadata = context.metadata or {}
    active_hazards = set(metadata.get("hazard_flags", []))
    if metadata.get("hazard_condition"):
        active_hazards.add(str(metadata["hazard_condition"]))

    for trigger in triggers:
        condition = trigger.get("condition")
        if not condition or condition not in active_hazards:
            continue
        decision = trigger.get("decision", "authorization_required")
        return EvaluationLayer(
            source="domain_overlay_hazard",
            decision=decision,
            reason=f"Domain overlay hazard trigger {condition} requires {decision}.",
        )
    return None


def _evidence_rank(evidence_state: str) -> int:
    if evidence_state.startswith("E") and len(evidence_state) > 1 and evidence_state[1].isdigit():
        return int(evidence_state[1])
    return 0


def tool_registry_decision(tool_spec: ToolSpec, requested_tool: str) -> EvaluationLayer | None:
    if not tool_spec.known and (tool_spec.mutates_state or tool_spec.external_effect):
        return EvaluationLayer(
            source="tool_registry",
            decision="abstain_insufficient_context",
            reason=f"Unknown mutating tool {requested_tool}; abstaining and blocking by default.",
        )
    perm = tool_spec.default_permission
    decision = PERMISSION_TO_DECISION.get(perm, perm)
    return EvaluationLayer(
        source="tool_registry",
        decision=decision,
        reason=f"Tool registry default permission for {requested_tool} is {decision}.",
    )


def mandatory_tool_declaration_decision(
    tool_spec: ToolSpec,
    requested_tool: str,
    context: AKTAContext,
    requested_action: str,
) -> EvaluationLayer | None:
    """A8 fail-closed: mutating tools require registry entry when NL-only classification."""
    if tool_spec.known:
        return None
    if not (tool_spec.mutates_state or tool_spec.external_effect):
        return None
    if context.structured_action or context.tool_payload:
        return None
    return EvaluationLayer(
        source="mandatory_tool_declaration",
        decision="abstain_insufficient_context",
        reason=(
            f"Mutating tool {requested_tool} is not in the registry and no structured "
            f"action declaration was provided; declare tool in registry or supply "
            f"structured_action before retry."
        ),
    )


def handoff_escalation_decision(context: AKTAContext) -> EvaluationLayer | None:
    chain = context.handoff_chain or []
    if len(chain) < 2:
        return None
    levels = [hop.get("responsibility_level", "") for hop in chain]
    ranks = [responsibility_rank(l) for l in levels if l]
    if not ranks:
        return None

    # Monotonic authority transfer: each hop escalates responsibility.
    monotonic_escalation = all(
        ranks[i] <= ranks[i + 1] for i in range(len(ranks) - 1)
    ) and ranks[-1] > ranks[0]

    if monotonic_escalation and ranks[-1] - ranks[0] >= 2:
        return EvaluationLayer(
            source="handoff_chain",
            decision="review_required",
            reason=(
                "Handoff chain shows monotonic authority transfer with "
                f"responsibility escalation {levels[0]} -> {levels[-1]}."
            ),
        )
    if max(ranks) - min(ranks) >= 3:
        return EvaluationLayer(
            source="handoff_chain",
            decision="review_required",
            reason="Multi-agent handoff shows responsibility escalation across the chain.",
        )
    if max(ranks) >= responsibility_rank("R6_resource_allocation"):
        return EvaluationLayer(
            source="handoff_chain",
            decision="review_required",
            reason="Handoff chain reaches resource allocation responsibility level.",
        )
    return None


def _draft_only_allowed_tools(
    policy: PolicyBundle,
    tool_spec: ToolSpec,
    requested_tool: str,
) -> list[str]:
    """Policy-driven draft-only allowlist from tool registry."""
    allowed: list[str] = []
    tools = policy.tool_registry.get("tools", {})
    for name, spec in tools.items():
        if spec.get("default_permission") == "draft_only" and not spec.get("mutates_state", False):
            allowed.append(name)
    if requested_tool in tools and not tool_spec.mutates_state:
        allowed.append(requested_tool)
    return sorted(set(allowed))


def _blocked_tools_closure(
    policy: PolicyBundle,
    action_type: str,
    requested_tool: str,
    tool_spec: ToolSpec,
) -> list[str]:
    """Expand blocked tools to action-type family and mutating siblings."""
    blocked = {requested_tool}
    tools = policy.tool_registry.get("tools", {})
    family = tools.get(requested_tool, {}).get("action_family")
    target_action = tool_spec.action_type

    for name, spec in tools.items():
        if spec.get("action_type") == target_action and spec.get("mutates_state"):
            blocked.add(name)
        if family and spec.get("action_family") == family and spec.get("mutates_state"):
            blocked.add(name)

    if action_type == "A7_resource_or_queue_prioritization":
        blocked.add("robot_queue.submit")
    if action_type == "A9_execution_adjacent_or_external_action":
        blocked.update(
            n for n, s in tools.items()
            if s.get("action_type") == "A9_execution_adjacent_or_external_action"
            and s.get("mutates_state")
        )
    return sorted(blocked)


def low_confidence_decision(
    confidence: float,
    tool_spec: ToolSpec,
    requested_tool: str,
    threshold: float = 0.7,
) -> EvaluationLayer | None:
    if confidence >= threshold:
        return None
    if tool_spec.mutates_state or tool_spec.external_effect or not tool_spec.known:
        return EvaluationLayer(
            source="classifier_confidence",
            decision="abstain_insufficient_context",
            reason=(
                f"Classifier confidence {confidence:.2f} below {threshold} for "
                f"mutating/external tool {requested_tool}; fail-closed."
            ),
        )
    return None


def next_admissible_steps_for(
    action_type: str,
    evidence_state: str,
    admissibility: str,
) -> list[str]:
    steps: list[str] = []
    if admissibility not in ("blocked", "abstain_insufficient_context"):
        return steps

    if action_type in ("A7_resource_or_queue_prioritization", "A4_recommendation"):
        steps.extend([
            "downgrade to hypothesis discussion",
            "draft a validation experiment",
            "request domain review before prioritization",
        ])
    elif action_type == "A5_protocol_modification":
        steps.extend([
            "produce draft-only protocol change",
            "request protocol owner review",
            "document rationale and evidence state",
        ])
    elif action_type == "A6_experimental_planning":
        steps.extend([
            "draft validation experiment plan only",
            "request review before activating plan",
            "gather additional evidence",
        ])
    elif action_type == "A9_execution_adjacent_or_external_action":
        steps.extend([
            "obtain explicit authorization",
            "reduce to draft planning stage",
            "route to domain safety review",
        ])
    elif action_type == "A10_publication_or_claim_escalation":
        steps.extend([
            "mark claim as preliminary",
            "request evidence review",
            "defer publication until validation",
        ])
    else:
        steps.extend([
            "clarify requested action and evidence context",
            "reduce action scope to admissible type",
            "request human review",
        ])

    if evidence_state in ("E0_no_evidence", "E1_anecdotal_or_informal_observation", "E2_preliminary_signal"):
        if "gather additional evidence" not in steps:
            steps.append("gather additional evidence")

    return steps


def required_review_role_for(
    overlay: DomainOverlay | None,
    action_type: str,
) -> str | None:
    if overlay is None:
        default_roles = {
            "A5_protocol_modification": "protocol_owner",
            "A6_experimental_planning": "domain_scientist",
            "A7_resource_or_queue_prioritization": "domain_scientist",
            "A8_tool_or_workflow_mutation": "workflow_owner",
            "A9_execution_adjacent_or_external_action": "lab_safety_officer",
            "A10_publication_or_claim_escalation": "domain_scientist",
        }
        return default_roles.get(action_type)

    roles = overlay.required_review_roles()
    key_map = {
        "A5_protocol_modification": "protocol_modification",
        "A7_resource_or_queue_prioritization": "queue_prioritization",
        "A8_tool_or_workflow_mutation": "tool_or_workflow_mutation",
        "A9_execution_adjacent_or_external_action": "execution_adjacent",
        "A10_publication_or_claim_escalation": "publication_claim",
    }
    key = key_map.get(action_type)
    if key and key in roles:
        return roles[key][0]
    return "domain_scientist"


def evaluate_admissibility(
    policy: PolicyBundle,
    profile: str,
    action_type: str,
    evidence_state: str,
    tool_spec: ToolSpec,
    requested_tool: str,
    context: AKTAContext,
    overlay: DomainOverlay | None = None,
    consequentiality: ConsequentialityResult | None = None,
    classifier_confidence: float = 0.95,
    ai_output: Any = None,
    requested_action: str = "",
) -> EvaluationResult:
    """Compose admissibility from all policy layers."""
    if consequentiality is None:
        consequentiality = classify_consequentiality(
            action_type, tool_spec, requested_tool, requested_action,
            ai_output, context, overlay,
        )

    layers: list[EvaluationLayer] = []

    prof = profile_decision(
        policy, profile, action_type, tool_spec, requested_tool, consequentiality
    )
    layers.append(
        EvaluationLayer(
            source="deployment_profile",
            decision=prof,
            reason=f"Profile {profile} matrix decision for {action_type} is {prof}.",
        )
    )

    ev_dec, ev_reason = evidence_decision(
        policy, evidence_state, action_type, profile,
        tool_spec, requested_tool, consequentiality,
    )
    if ev_dec:
        layers.append(EvaluationLayer(source="evidence_rules", decision=ev_dec, reason=ev_reason))

    layers.extend(overlay_decision(overlay, action_type, evidence_state, requested_tool))

    hazard_layer = hazard_trigger_decision(overlay, context)
    if hazard_layer:
        layers.append(hazard_layer)

    tool_layer = tool_registry_decision(tool_spec, requested_tool)
    if tool_layer:
        layers.append(tool_layer)

    mandatory_layer = mandatory_tool_declaration_decision(
        tool_spec, requested_tool, context, requested_action
    )
    if mandatory_layer:
        layers.append(mandatory_layer)

    handoff_layer = handoff_escalation_decision(context)
    if handoff_layer:
        layers.append(handoff_layer)

    conf_layer = low_confidence_decision(classifier_confidence, tool_spec, requested_tool)
    if conf_layer:
        layers.append(conf_layer)

    prior_review_layer = evaluate_prior_review(
        context.metadata, action_type, requested_tool, tool_spec
    )
    if prior_review_layer:
        layers.append(prior_review_layer)

    prior_records_layer = evaluate_prior_akta_records(context.prior_akta_records, action_type)
    if prior_records_layer:
        layers.append(prior_records_layer)

    disclaimer_layer = evaluate_disclaimer_boundary(context.metadata, tool_spec, requested_tool)
    if disclaimer_layer:
        layers.append(disclaimer_layer)

    final = strictest(*(layer.decision for layer in layers))
    reasons = [layer.reason for layer in layers if layer.decision == final]
    if not reasons:
        reasons = [layer.reason for layer in layers]

    review_role = required_review_role_for(overlay, action_type)
    blocked_tools: list[str] = []
    allowed_tools: list[str] = []

    if final in ("blocked", "abstain_insufficient_context", "authorization_required", "review_required"):
        blocked_tools = _blocked_tools_closure(policy, action_type, requested_tool, tool_spec)
    elif final == "draft_only":
        blocked_tools = [requested_tool] if tool_spec.mutates_state else []
        allowed_tools = _draft_only_allowed_tools(policy, tool_spec, requested_tool)
        if requested_tool in VALIDATION_DRAFT_TOOLS or not tool_spec.mutates_state:
            if requested_tool not in allowed_tools:
                allowed_tools.append(requested_tool)
    else:
        allowed_tools = [requested_tool]

    if final != "draft_only" and not allowed_tools:
        if final not in ("blocked", "abstain_insufficient_context", "authorization_required", "review_required"):
            allowed_tools = [requested_tool]

    next_steps = next_admissible_steps_for(action_type, evidence_state, final)

    return EvaluationResult(
        admissibility=final,
        layers=layers,
        decision_reason=" ".join(reasons[:2]) if reasons else f"Final decision: {final}.",
        required_review_role=review_role if final in ("review_required", "authorization_required") else None,
        blocked_tools=sorted(set(blocked_tools)),
        allowed_tools=sorted(set(allowed_tools)),
        next_admissible_steps=next_steps,
        review_required=final == "review_required",
        authorization_required=final == "authorization_required",
        record_required=final != "allowed",
        consequentiality=consequentiality.consequential,
        consequentiality_reason=consequentiality.reason,
    )
