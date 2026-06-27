"""Tool registry resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from akta.errors import ToolRegistryError


@dataclass
class ToolSpec:
    """Resolved tool specification."""

    name: str
    action_type: str
    mutates_state: bool
    external_effect: bool
    default_permission: str
    known: bool = True


class ToolRegistry:
    """AKTA tool registry."""

    def __init__(self, registry_data: dict[str, Any]) -> None:
        self.version = registry_data.get("version", "akta-tool-registry-v0.1")
        self.tools: dict[str, dict[str, Any]] = registry_data.get("tools", {})

    def resolve(self, tool_name: str) -> ToolSpec:
        if tool_name in self.tools:
            spec = self.tools[tool_name]
            return ToolSpec(
                name=tool_name,
                action_type=spec["action_type"],
                mutates_state=bool(spec.get("mutates_state", False)),
                external_effect=bool(spec.get("external_effect", False)),
                default_permission=spec.get("default_permission", "review_required"),
                known=True,
            )
        return ToolSpec(
            name=tool_name,
            action_type="A8_tool_or_workflow_mutation",
            mutates_state=True,
            external_effect=False,
            default_permission="abstain_insufficient_context",
            known=False,
        )

    def list_tools(self) -> list[str]:
        return sorted(self.tools.keys())

    def validate_tool_exists(self, tool_name: str) -> None:
        if tool_name not in self.tools:
            raise ToolRegistryError(f"Unknown tool: {tool_name}")
