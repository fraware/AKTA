"""OpenAI guardrail adapter — AKTA gate before tool execution."""

from __future__ import annotations

from typing import Any, Callable

from akta.context import AKTAContext
from akta.errors import AKTAReviewRequired
from akta.gate import AKTAGate


class OpenAIGuardrailAdapter:
    """Thin wrapper: run AKTA gate before OpenAI-style tool calls.

    Usage:
        adapter = OpenAIGuardrailAdapter()
        gated_fn = adapter.wrap_tool(my_tool_fn, "lab_scheduler.prioritize")
    """

    def __init__(
        self,
        policy_dir: str = "policy",
        overlays_dir: str = "overlays",
        deployment_profile: str = "P2_analysis_assistant",
    ) -> None:
        self.gate = AKTAGate.from_policy_dir(policy_dir, overlays_dir=overlays_dir)
        self.deployment_profile = deployment_profile

    def check_tool_call(
        self,
        tool_name: str,
        action_name: str,
        *,
        ai_output: Any = "",
        context: dict[str, Any] | None = None,
        domain_overlay: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate admissibility; raise on block/review/auth."""
        decision = self.gate.evaluate(
            ai_output=ai_output,
            requested_tool=tool_name,
            requested_action=action_name,
            context=AKTAContext.from_dict(context or {}),
            deployment_profile=self.deployment_profile,
            domain_overlay=domain_overlay,
        )
        d = decision.to_dict()
        if decision.admissibility == "review_required":
            raise AKTAReviewRequired(
                tool_name,
                trigger=d.get("review_trigger"),
                reason=d.get("decision_reason", ""),
            )
        if decision.admissibility in ("blocked", "abstain_insufficient_context", "authorization_required"):
            raise PermissionError(
                f"AKTA blocked {tool_name}: {d['admissibility']} — {d['decision_reason']}"
            )
        return d

    def wrap_tool(
        self,
        tool_fn: Callable[..., Any],
        tool_name: str,
        action_name: str | None = None,
    ) -> Callable[..., Any]:
        action = action_name or tool_name.split(".")[-1]

        def gated(*args: Any, **kwargs: Any) -> Any:
            self.check_tool_call(
                tool_name,
                action,
                ai_output=kwargs.pop("ai_output", kwargs.get("summary", "")),
                context=kwargs.pop("context", {}),
                domain_overlay=kwargs.pop("domain_overlay", None),
            )
            return tool_fn(*args, **kwargs)

        return gated
