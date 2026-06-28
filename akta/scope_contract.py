"""SCOPE-compatible contract helpers for AKTA review triggers and packets.

When the SCOPE repository is not available locally, these helpers mirror the
field extraction and approval_scopes validation that SCOPE performs on AKTA
review triggers and review packets.
"""

from __future__ import annotations

from typing import Any

from akta.scope_mapping import VALID_REQUESTED_SCOPES

SCOPE_APPROVAL_SCOPES = frozenset(VALID_REQUESTED_SCOPES)

# v0.2 review_scope vocabulary -> v0.3 requested_scope (compat for SCOPE simulator).
LEGACY_REVIEW_SCOPE_MAP: dict[str, str] = {
    "draft_only": "protocol_draft",
    "protocol_draft": "protocol_draft",
    "active_protocol": "active_protocol_update",
    "active_protocol_update": "active_protocol_update",
    "run_plan": "single_validation_plan",
    "single_validation_plan": "single_validation_plan",
    "validation_draft": "single_validation_run_draft",
    "single_validation_run_draft": "single_validation_run_draft",
    "queue_prioritization": "single_run_queue_priority",
    "single_run_queue_priority": "single_run_queue_priority",
    "robot_submission": "robot_queue_submission",
    "robot_queue_submission": "robot_queue_submission",
    "execution_preparation": "execution_payload_preparation",
    "execution_payload_preparation": "execution_payload_preparation",
    "publication_claim": "publication_claim",
    "scientific_memory_import": "scientific_memory_import",
}


def resolve_trigger_requested_scope(trigger: dict[str, Any]) -> str | None:
    """Resolve requested_scope from v0.3 field or legacy review_scope fallback."""
    scope = trigger.get("requested_scope")
    if scope in SCOPE_APPROVAL_SCOPES:
        return scope
    legacy = trigger.get("review_scope")
    if legacy:
        mapped = LEGACY_REVIEW_SCOPE_MAP.get(str(legacy))
        if mapped in SCOPE_APPROVAL_SCOPES:
            return mapped
    return None


def extract_scope_fields(trigger: dict[str, Any]) -> dict[str, Any]:
    """Extract SCOPE-consumed fields from an AKTA review trigger."""
    return {
        "review_trigger_id": trigger.get("review_trigger_id"),
        "review_trigger_version": trigger.get("review_trigger_version"),
        "akta_decision_id": trigger.get("akta_decision_id") or trigger.get("decision_id"),
        "akta_record_id": trigger.get("akta_record_id") or trigger.get("source_record_id"),
        "requested_scope": resolve_trigger_requested_scope(trigger),
        "review_route": trigger.get("review_route"),
        "required_review_role": trigger.get("required_review_role"),
        "blocked_tools": list(trigger.get("blocked_tools") or []),
        "allowed_next_steps": list(trigger.get("allowed_next_steps") or []),
        "policy_hash": trigger.get("policy_hash"),
        "tool_registry_hash": trigger.get("tool_registry_hash"),
    }


def validate_requested_scope(trigger: dict[str, Any]) -> None:
    """Raise ValueError if requested_scope is missing or not a SCOPE approval scope."""
    scope = resolve_trigger_requested_scope(trigger)
    if not scope:
        legacy = trigger.get("review_scope")
        if legacy:
            raise ValueError(f"invalid legacy review_scope: {legacy}")
        raise ValueError("review trigger missing required requested_scope")


def validate_approval_grant(
    *,
    granted_scope: str,
    requested_scope: str,
    allowed_tools: list[str] | None = None,
    blocked_tools: list[str] | None = None,
) -> dict[str, Any]:
    """Simulate SCOPE scoped grant validation (authority-transfer boundary)."""
    if granted_scope not in SCOPE_APPROVAL_SCOPES:
        raise ValueError(f"invalid granted_scope: {granted_scope}")

    scope_ok = granted_scope == requested_scope or (
        requested_scope == "active_protocol_update" and granted_scope == "protocol_draft"
    )
    if not scope_ok:
        raise ValueError(
            f"grant scope {granted_scope} does not cover requested_scope {requested_scope}"
        )

    return {
        "granted_scope": granted_scope,
        "requested_scope": requested_scope,
        "allowed_tools": allowed_tools or [],
        "blocked_tools": blocked_tools or [],
        "scope_covered": granted_scope == requested_scope,
        "narrow_draft_grant": (
            requested_scope == "active_protocol_update" and granted_scope == "protocol_draft"
        ),
    }


def assemble_review_packet(
    trigger: dict[str, Any],
    record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a SCOPE review packet from trigger-only, record-only, or combined inputs."""
    validate_requested_scope(trigger)
    packet: dict[str, Any] = {
        "packet_type": "scope_review_packet",
        "trigger": extract_scope_fields(trigger),
    }
    if record is not None:
        packet["record"] = {
            "record_id": record.get("record_id"),
            "record_hash": record.get("record_hash"),
            "classification": record.get("classification"),
            "decision": record.get("decision"),
        }
        packet["packet_mode"] = "trigger_plus_record"
    else:
        packet["packet_mode"] = "trigger_only"
    return packet
