"""MCP-style tool wrapper for AKTA gate evaluation."""

from __future__ import annotations

from typing import Any

from akta.context import AKTAContext
from akta.gate import AKTAGate


class AKTAMCPWrapper:
    """Wrap AKTA gate as an MCP-compatible tool evaluator."""

    def __init__(
        self,
        policy_dir: str = "policy",
        overlays_dir: str = "overlays",
    ) -> None:
        self.gate = AKTAGate.from_policy_dir(policy_dir, overlays_dir=overlays_dir)

    def tool_spec(self) -> dict[str, Any]:
        return {
            "name": "akta_evaluate",
            "description": "Evaluate scientific action admissibility before tool execution.",
            "inputSchema": {
                "type": "object",
                "required": ["requested_tool"],
                "properties": {
                    "ai_output": {},
                    "requested_tool": {"type": "string"},
                    "requested_action": {"type": "string"},
                    "deployment_profile": {"type": "string"},
                    "domain_overlay": {"type": "string"},
                    "context": {"type": "object"},
                },
            },
        }

    def call(self, arguments: dict[str, Any]) -> dict[str, Any]:
        decision = self.gate.evaluate(
            ai_output=arguments.get("ai_output", ""),
            requested_tool=arguments["requested_tool"],
            requested_action=arguments.get("requested_action", arguments["requested_tool"]),
            context=AKTAContext.from_dict(arguments.get("context", {})),
            deployment_profile=arguments.get("deployment_profile", "P2_analysis_assistant"),
            domain_overlay=arguments.get("domain_overlay"),
        )
        d = decision.to_dict()
        return {
            "admissibility": d["admissibility"],
            "blocked_tools": d.get("blocked_tools", []),
            "allowed_tools": d.get("allowed_tools", []),
            "next_admissible_steps": d.get("next_admissible_steps", []),
            "policy_hash": d["policy_hash"],
        }
