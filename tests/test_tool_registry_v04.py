"""Tool registry coverage for v0.4 (25+ tools)."""

from __future__ import annotations

from pathlib import Path

from akta.policy import PolicyBundle
from akta.tool_registry import ToolRegistry

ROOT = Path(__file__).resolve().parent.parent


def test_tool_registry_has_25_plus_tools() -> None:
    policy = PolicyBundle.from_dir(ROOT / "policy")
    registry = ToolRegistry(policy.tool_registry)
    tools = registry.list_tools()
    assert len(tools) >= 25


def test_scientific_memory_import_is_a8_mutating() -> None:
    policy = PolicyBundle.from_dir(ROOT / "policy")
    registry = ToolRegistry(policy.tool_registry)
    spec = registry.resolve("scientific_memory.import")
    assert spec.known is True
    assert spec.action_type == "A8_tool_or_workflow_mutation"
    assert spec.mutates_state is True
