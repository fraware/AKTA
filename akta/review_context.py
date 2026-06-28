"""Review context enforcement for prior review metadata and AKTA records."""

from __future__ import annotations

from typing import Any

from akta.classify import action_rank
from akta.evaluation_types import EvaluationLayer
from akta.tool_registry import ToolSpec

# Prior review scope vocabulary -> maximum allowed action rank (lower = less consequential).
PRIOR_SCOPE_MAX_ACTION: dict[str, str] = {
    "draft_only": "A6_experimental_planning",
    "protocol_draft": "A5_protocol_modification",
    "single_validation_plan": "A6_experimental_planning",
    "single_validation_run_draft": "A6_experimental_planning",
    "single_run_queue_priority": "A7_resource_or_queue_prioritization",
    "active_protocol_update": "A5_protocol_modification",
    "robot_queue_submission": "A9_execution_adjacent_or_external_action",
    "execution_payload_preparation": "A9_execution_adjacent_or_external_action",
    "publication_claim": "A10_publication_or_claim_escalation",
    "scientific_memory_import": "A8_tool_or_workflow_mutation",
}

# draft_only scope only permits non-mutating draft tools.
DRAFT_ONLY_ALLOWED_TOOLS = frozenset({
    "experiment_planner.create_validation_draft",
    "protocol_editor.draft_change",
    "publication.draft_claim",
    "ehr.draft_note",
})


def _metadata_value(metadata: dict[str, Any], key: str) -> Any:
    return metadata.get(key)


def evaluate_prior_review(
    metadata: dict[str, Any] | None,
    action_type: str,
    requested_tool: str,
    tool_spec: ToolSpec,
) -> EvaluationLayer | None:
    """F14: enforce prior review validity, expiration, and scope boundaries."""
    if not metadata:
        return None

    prior_id = _metadata_value(metadata, "prior_review_id")
    if not prior_id:
        return None

    expired = bool(_metadata_value(metadata, "prior_review_expired"))
    prior_scope = str(_metadata_value(metadata, "prior_review_scope") or "")
    prior_decision = str(_metadata_value(metadata, "prior_review_decision") or "")

    if prior_decision == "denied":
        return EvaluationLayer(
            source="review_context",
            decision="blocked",
            reason=f"Prior review {prior_id} was denied; repeating blocked action.",
        )

    scope_exceeded = _scope_exceeded(prior_scope, action_type, requested_tool, tool_spec)
    if scope_exceeded:
        return EvaluationLayer(
            source="review_context",
            decision="blocked",
            reason=(
                f"Prior review {prior_id} scope {prior_scope} does not cover "
                f"{requested_tool} ({action_type})."
            ),
        )

    if expired:
        return EvaluationLayer(
            source="review_context",
            decision="review_required",
            reason=(
                f"Prior review {prior_id} expired (scope={prior_scope}); "
                f"new review required before {action_type}."
            ),
        )

    return None


def _scope_exceeded(
    prior_scope: str,
    action_type: str,
    requested_tool: str,
    tool_spec: ToolSpec,
) -> bool:
    if prior_scope == "draft_only":
        if action_rank(action_type) >= action_rank("A7_resource_or_queue_prioritization"):
            return True
        if tool_spec.mutates_state and requested_tool not in DRAFT_ONLY_ALLOWED_TOOLS:
            return True
        return False

    max_action = PRIOR_SCOPE_MAX_ACTION.get(prior_scope)
    if max_action and action_rank(action_type) > action_rank(max_action):
        return True
    return False


def evaluate_prior_akta_records(
    prior_records: list[dict[str, Any]] | None,
    action_type: str,
) -> EvaluationLayer | None:
    """Tighten decision when prior AKTA records show blocked escalation."""
    if not prior_records:
        return None

    current_rank = action_rank(action_type)
    for record in prior_records:
        decision_block = record.get("decision", {})
        prior_adm = decision_block.get("admissibility", "")
        prior_action = record.get("classification", {}).get("scientific_action_type", "")
        if prior_adm in ("blocked", "abstain_insufficient_context") and prior_action:
            if current_rank > action_rank(prior_action):
                return EvaluationLayer(
                    source="prior_akta_records",
                    decision="blocked",
                    reason=(
                        f"Prior record blocked {prior_action}; escalation to "
                        f"{action_type} is not permitted."
                    ),
                )
        if prior_adm == "review_required" and current_rank > action_rank(prior_action or action_type):
            return EvaluationLayer(
                source="prior_akta_records",
                decision="review_required",
                reason=(
                    f"Prior record required review for {prior_action}; "
                    f"escalation to {action_type} requires new review."
                ),
            )
    return None


def evaluate_disclaimer_boundary(
    metadata: dict[str, Any] | None,
    tool_spec: ToolSpec,
    requested_tool: str,
) -> EvaluationLayer | None:
    """F12: disclaimer without action boundary on mutating tools escalates."""
    if not metadata:
        return None
    disclaimer = metadata.get("disclaimer") or metadata.get("ai_disclaimer")
    if not disclaimer:
        return None
    has_boundary = bool(
        metadata.get("action_boundary")
        or metadata.get("permitted_actions")
        or metadata.get("scope_boundary")
    )
    if has_boundary:
        return None
    if tool_spec.mutates_state or tool_spec.external_effect:
        return EvaluationLayer(
            source="disclaimer_metadata",
            decision="review_required",
            reason=(
                f"Disclaimer present without action boundary on mutating tool "
                f"{requested_tool}; escalating to review."
            ),
        )
    return None
