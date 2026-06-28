"""SCOPE requested_scope and review_route resolution (v0.3)."""

from __future__ import annotations

from typing import Any

from akta.overlays import DomainOverlay

VALID_REQUESTED_SCOPES = frozenset({
    "protocol_draft",
    "active_protocol_update",
    "single_validation_plan",
    "single_validation_run_draft",
    "single_run_queue_priority",
    "robot_queue_submission",
    "execution_payload_preparation",
    "publication_claim",
    "scientific_memory_import",
})

REVIEW_TRIGGER_VERSION = "0.3"


def _tool_entry(scope_config: dict[str, Any], requested_tool: str) -> dict[str, Any] | None:
    tools = scope_config.get("tools", {})
    entry = tools.get(requested_tool)
    return dict(entry) if isinstance(entry, dict) else None


def _action_type_scope(
    scope_config: dict[str, Any],
    action_type: str,
    requested_tool: str,
) -> str | None:
    defaults = scope_config.get("action_type_defaults", {})
    cfg = defaults.get(action_type)
    if not isinstance(cfg, dict):
        return None

    if action_type == "A5_protocol_modification":
        draft_tools = set(cfg.get("draft_tools", []))
        if requested_tool in draft_tools:
            return cfg.get("draft_scope")
        return cfg.get("active_scope")

    if action_type == "A6_experimental_planning":
        draft_tools = set(cfg.get("validation_draft_tools", []))
        if requested_tool in draft_tools:
            return cfg.get("validation_draft_scope")
        return cfg.get("plan_scope")

    if action_type == "A9_execution_adjacent_or_external_action":
        robot_tools = set(cfg.get("robot_tools", []))
        if requested_tool in robot_tools:
            return cfg.get("robot_scope")
        return cfg.get("default_scope")

    return cfg.get("default_scope")


def resolve_requested_scope(
    *,
    scope_config: dict[str, Any],
    requested_tool: str,
    action_type: str,
    overlay: DomainOverlay | None = None,
) -> str:
    """Resolve SCOPE requested_scope; never returns invalid enum values."""
    if overlay is not None:
        overrides = overlay.data.get("requested_scope_overrides", {})
        if requested_tool in overrides:
            scope = overrides[requested_tool]
            if scope in VALID_REQUESTED_SCOPES:
                return scope

    entry = _tool_entry(scope_config, requested_tool)
    if entry and entry.get("requested_scope") in VALID_REQUESTED_SCOPES:
        return entry["requested_scope"]

    from_action = _action_type_scope(scope_config, action_type, requested_tool)
    if from_action in VALID_REQUESTED_SCOPES:
        return from_action

    # Fail-closed fallback by action family — still valid SCOPE scopes only.
    family_fallback = {
        "A5_protocol_modification": "protocol_draft",
        "A6_experimental_planning": "single_validation_plan",
        "A7_resource_or_queue_prioritization": "single_run_queue_priority",
        "A8_tool_or_workflow_mutation": "execution_payload_preparation",
        "A9_execution_adjacent_or_external_action": "execution_payload_preparation",
        "A10_publication_or_claim_escalation": "publication_claim",
    }
    scope = family_fallback.get(action_type, "single_validation_plan")
    assert scope in VALID_REQUESTED_SCOPES
    return scope


def resolve_review_route(
    *,
    scope_config: dict[str, Any],
    requested_scope: str,
    requested_tool: str,
) -> str | None:
    """Human/process routing hint; optional for SCOPE packet assembly."""
    entry = _tool_entry(scope_config, requested_tool)
    if entry and entry.get("review_route"):
        return str(entry["review_route"])

    defaults = scope_config.get("review_route_defaults", {})
    route = defaults.get(requested_scope)
    return str(route) if route else None
