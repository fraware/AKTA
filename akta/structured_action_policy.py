"""Structured action schema enforcement for mutating tools (v1.0)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from akta.context import AKTAContext
from akta.evaluation_types import EvaluationLayer
from akta.tool_registry import ToolSpec


@lru_cache(maxsize=8)
def load_structured_action_schema(policy_dir: str) -> dict[str, Any] | None:
    path = Path(policy_dir) / "structured_action_schema.yaml"
    if not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def structured_action_requirement_decision(
    tool_spec: ToolSpec,
    requested_tool: str,
    context: AKTAContext,
    *,
    policy_dir: str | Path,
) -> EvaluationLayer | None:
    """Fail-closed when mutating tools lack required structured_action fields."""
    schema = load_structured_action_schema(str(policy_dir))
    if not schema or not schema.get("mutating_tools_require_declaration"):
        return None
    if not (tool_spec.mutates_state or tool_spec.external_effect):
        return None

    declaration = context.structured_action or context.tool_payload
    required = list(schema.get("required_fields") or [])

    if declaration:
        missing = [f for f in required if f not in declaration]
        if not missing:
            return None
        return EvaluationLayer(
            source="structured_action_schema",
            decision="abstain_insufficient_context",
            reason=(
                f"Mutating tool {requested_tool} structured_action missing fields: "
                f"{', '.join(missing)}"
            ),
        )

    if tool_spec.known:
        return None

    return EvaluationLayer(
        source="structured_action_schema",
        decision="abstain_insufficient_context",
        reason=(
            f"Mutating tool {requested_tool} requires structured_action declaration "
            f"per {schema.get('version', 'structured_action_schema')}"
        ),
    )
