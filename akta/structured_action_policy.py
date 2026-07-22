"""Structured action schema enforcement for mutating tools (directive §7)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from akta.capability_envelope import CAPABILITY_FAMILIES
from akta.context import AKTAContext
from akta.evaluation_types import EvaluationLayer
from akta.policy_integrity import is_production_mode, require_signed_policy
from akta.tool_registry import ToolSpec

KNOWN_ACTION_TYPES = frozenset({
    "A0_informational_or_exploratory",
    "A1_retrieval_or_summary",
    "A2_analysis_or_interpretation",
    "A3_hypothesis_generation",
    "A4_recommendation",
    "A5_protocol_modification",
    "A6_experimental_planning",
    "A7_resource_or_queue_prioritization",
    "A8_tool_or_workflow_mutation",
    "A9_execution_adjacent_or_external_action",
    "A10_publication_or_claim_escalation",
})

TOOL_FAMILY_HINTS: dict[str, str] = {
    "literature": "scientific_interpretation",
    "protocol": "protocol",
    "experiment": "experiment_plan",
    "lab_scheduler": "queue_allocation",
    "robot": "execution",
    "publication": "publication",
    "memory": "scientific_memory",
    "ehr": "recommendation",
}


@lru_cache(maxsize=8)
def load_structured_action_schema(policy_dir: str) -> dict[str, Any] | None:
    path = Path(policy_dir) / "structured_action_schema.yaml"
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not data.get("version"):
        # Unversioned schemas are rejected at enforcement time.
        data["_unversioned"] = True
    return data


def require_structured_actions_for_known_tools(schema: dict[str, Any]) -> bool:
    """Resolve whether known mutating tools require declarations."""
    env = os.environ.get("AKTA_REQUIRE_STRUCTURED_ACTIONS", "").strip().lower()
    if env in ("1", "true", "yes"):
        return True
    if env in ("0", "false", "no"):
        return False
    grant_mode = os.environ.get("AKTA_GRANT_MODE", "").strip().lower()
    if grant_mode in ("pilot", "release", "cross_repo", "production"):
        return True
    if is_production_mode() or require_signed_policy():
        return True
    return bool(schema.get("require_for_known_mutating_tools", True))


def default_structured_action_for_tool(
    requested_tool: str,
    requested_action: str,
    *,
    external_effect: bool = False,
) -> dict[str, Any]:
    """Minimal valid declaration used for corpus backfill / eval harness."""
    payload: dict[str, Any] = {
        "tool_name": requested_tool,
        "action_intent": requested_action or "unspecified",
        "target_resource": requested_tool.split(".", 1)[0] if "." in requested_tool else requested_tool,
        "schema_version": "akta-structured-action-v1.0",
    }
    if external_effect:
        payload["external_effects_declared"] = True
        payload["external_effects"] = ["external"]
    return payload


def _tool_family(tool_name: str) -> str | None:
    prefix = tool_name.split(".", 1)[0]
    for key, family in TOOL_FAMILY_HINTS.items():
        if key in prefix or prefix.startswith(key):
            return family
    return None


def validate_structured_action_declaration(
    declaration: dict[str, Any],
    *,
    tool_spec: ToolSpec,
    requested_tool: str,
    schema: dict[str, Any],
) -> list[str]:
    """Return validation errors for a structured_action declaration."""
    errors: list[str] = []
    if schema.get("_unversioned") or not schema.get("version"):
        errors.append("structured_action schema is unversioned; refusing enforcement")

    required = list(schema.get("required_fields") or [])
    for field in required:
        if field not in declaration:
            errors.append(f"missing required field: {field}")

    action_type = declaration.get("action_type")
    if action_type is not None and action_type not in KNOWN_ACTION_TYPES:
        errors.append(f"unknown action type: {action_type!r}")

    declared_tool = declaration.get("tool_name")
    if declared_tool and declared_tool != requested_tool:
        errors.append(
            f"tool_name mismatch: declaration {declared_tool!r} != requested {requested_tool!r}"
        )

    family = declaration.get("capability_family") or declaration.get("action_family")
    if family and family not in CAPABILITY_FAMILIES:
        errors.append(f"unknown capability_family: {family!r}")
    tool_family = _tool_family(requested_tool)
    if family and tool_family and family != tool_family:
        errors.append(
            f"action/tool family mismatch: declaration {family!r} vs tool hint {tool_family!r}"
        )

    target = declaration.get("target_resource") or declaration.get("target")
    expected_target = declaration.get("expected_target")
    if expected_target and target and str(expected_target) != str(target):
        errors.append(
            f"target mismatch: expected {expected_target!r}, got {target!r}"
        )

    if tool_spec.external_effect and not declaration.get("external_effects_declared"):
        # Allow explicit empty list as declared-none; missing key is undeclared.
        if "external_effects" not in declaration and "external_effects_declared" not in declaration:
            errors.append(
                f"mutating tool {requested_tool} declares external effects in registry "
                "but structured_action omits external_effects / external_effects_declared"
            )

    if not tool_spec.known and (tool_spec.mutates_state or tool_spec.external_effect):
        # Unknown mutating tools always require a complete declaration (already checked).
        pass

    return errors


def structured_action_requirement_decision(
    tool_spec: ToolSpec,
    requested_tool: str,
    context: AKTAContext,
    *,
    policy_dir: str | Path,
) -> EvaluationLayer | None:
    """Fail-closed when consequential mutating tools lack valid structured_action."""
    schema = load_structured_action_schema(str(policy_dir))
    if not schema or not schema.get("mutating_tools_require_declaration"):
        return None
    if not (tool_spec.mutates_state or tool_spec.external_effect):
        return None

    require_known = require_structured_actions_for_known_tools(schema)
    declaration = context.structured_action or context.tool_payload

    if not declaration:
        if tool_spec.known and not require_known:
            return None
        return EvaluationLayer(
            source="structured_action_schema",
            decision="abstain_insufficient_context",
            reason=(
                f"Mutating tool {requested_tool} requires structured_action declaration "
                f"per {schema.get('version', 'structured_action_schema')}"
            ),
        )

    if not isinstance(declaration, dict):
        return EvaluationLayer(
            source="structured_action_schema",
            decision="abstain_insufficient_context",
            reason=f"structured_action for {requested_tool} must be an object",
        )

    errors = validate_structured_action_declaration(
        declaration,
        tool_spec=tool_spec,
        requested_tool=requested_tool,
        schema=schema,
    )
    if errors:
        return EvaluationLayer(
            source="structured_action_schema",
            decision="abstain_insufficient_context",
            reason=f"structured_action invalid for {requested_tool}: {'; '.join(errors)}",
        )
    return None
