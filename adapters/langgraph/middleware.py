"""LangGraph-style middleware for AKTA pre-action gating."""

from __future__ import annotations

from typing import Any, Callable

from akta.context import AKTAContext
from akta.gate import AKTAGate


class AKTALangGraphMiddleware:
    """Intercept tool calls and gate through AKTA before execution."""

    def __init__(
        self,
        policy_dir: str = "policy",
        overlays_dir: str = "overlays",
        deployment_profile: str = "P2_analysis_assistant",
        domain_overlay: str | None = None,
    ) -> None:
        self.gate = AKTAGate.from_policy_dir(policy_dir, overlays_dir=overlays_dir)
        self.deployment_profile = deployment_profile
        self.domain_overlay = domain_overlay

    def wrap_tool(
        self,
        tool_fn: Callable[..., Any],
        tool_name: str,
        action_name: str | None = None,
    ) -> Callable[..., Any]:
        action = action_name or tool_name.split(".")[-1]

        def gated(*args: Any, **kwargs: Any) -> Any:
            ai_output = kwargs.pop("ai_output", kwargs.get("summary", ""))
            context = kwargs.pop("context", {})
            decision = self.gate.evaluate(
                ai_output=ai_output,
                requested_tool=tool_name,
                requested_action=action,
                context=AKTAContext.from_dict(context if isinstance(context, dict) else {}),
                deployment_profile=kwargs.pop("deployment_profile", self.deployment_profile),
                domain_overlay=kwargs.pop("domain_overlay", self.domain_overlay),
            )
            if decision.admissibility in (
                "blocked",
                "abstain_insufficient_context",
                "authorization_required",
                "review_required",
            ):
                d = decision.to_dict()
                raise PermissionError(
                    f"AKTA blocked {tool_name}: {d['admissibility']} — {d['decision_reason']}"
                )
            return tool_fn(*args, **kwargs)

        return gated
