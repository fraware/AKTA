"""Anthropic guardrail adapter — AKTA gate before tool execution."""

from __future__ import annotations

from typing import Any, Callable

from akta.context import AKTAContext
from akta.errors import AKTAReviewRequired
from akta.gate import AKTAGate


class AnthropicGuardrailAdapter:
    """Thin wrapper: run AKTA gate before Anthropic-style tool_use blocks.

    Mirrors ``OpenAIGuardrailAdapter`` for Claude tool execution pipelines.
    """

    def __init__(
        self,
        policy_dir: str = "policy",
        overlays_dir: str = "overlays",
        deployment_profile: str = "P2_analysis_assistant",
    ) -> None:
        self.gate = AKTAGate.from_policy_dir(policy_dir, overlays_dir=overlays_dir)
        self.deployment_profile = deployment_profile

    def evaluate_tool_use(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        ai_output: Any = "",
        context: dict[str, Any] | None = None,
        domain_overlay: str | None = None,
    ) -> dict[str, Any]:
        action = str(tool_input.get("action") or tool_name.split(".")[-1])
        decision = self.gate.evaluate(
            ai_output=ai_output,
            requested_tool=tool_name,
            requested_action=action,
            context=AKTAContext.from_dict(context or {}),
            deployment_profile=self.deployment_profile,
            domain_overlay=domain_overlay,
        )
        d = decision.to_dict()
        if decision.admissibility == "review_required":
            raise AKTAReviewRequired(tool_name, trigger=d.get("review_trigger"), reason=d["decision_reason"])
        if decision.admissibility in ("blocked", "abstain_insufficient_context", "authorization_required"):
            raise PermissionError(f"AKTA blocked {tool_name}: {d['admissibility']}")
        return d

    def wrap_tool(
        self,
        tool_fn: Callable[..., Any],
        tool_name: str,
    ) -> Callable[..., Any]:
        def gated(tool_input: dict[str, Any], **kwargs: Any) -> Any:
            self.evaluate_tool_use(
                tool_name,
                tool_input,
                ai_output=kwargs.pop("ai_output", ""),
                context=kwargs.pop("context", {}),
            )
            return tool_fn(tool_input, **kwargs)

        return gated
