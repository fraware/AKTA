"""LangGraph-style middleware for AKTA pre-action gating."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from akta.context import AKTAContext
from akta.errors import AKTAReviewRequired
from akta.gate import AKTAGate
from akta.tool_registry import ToolRegistry


@dataclass
class GateResult:
    """Structured gate outcome for LangGraph integration."""

    admissibility: str
    allowed: bool
    decision: dict[str, Any]
    review_trigger: dict[str, Any] | None = None


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
        self.registry = ToolRegistry(self.gate.policy.tool_registry)
        self.deployment_profile = deployment_profile
        self.domain_overlay = domain_overlay

    def evaluate_tool(
        self,
        tool_name: str,
        action_name: str,
        *,
        ai_output: Any = "",
        context: dict[str, Any] | None = None,
    ) -> GateResult:
        decision = self.gate.evaluate(
            ai_output=ai_output,
            requested_tool=tool_name,
            requested_action=action_name,
            context=AKTAContext.from_dict(context or {}),
            deployment_profile=self.deployment_profile,
            domain_overlay=self.domain_overlay,
        )
        d = decision.to_dict()
        adm = decision.admissibility
        allowed = adm in ("allowed", "allowed_with_logging", "draft_only")
        if adm == "draft_only":
            spec = self.registry.resolve(tool_name)
            if spec.mutates_state:
                allowed = False
        return GateResult(
            admissibility=adm,
            allowed=allowed,
            decision=d,
            review_trigger=d.get("review_trigger"),
        )

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
            result = self.evaluate_tool(
                tool_name, action, ai_output=ai_output, context=context if isinstance(context, dict) else {}
            )
            if result.admissibility == "review_required":
                raise AKTAReviewRequired(
                    tool_name,
                    trigger=result.review_trigger,
                    reason=result.decision.get("decision_reason", ""),
                )
            if result.admissibility in ("blocked", "abstain_insufficient_context", "authorization_required"):
                raise PermissionError(
                    f"AKTA blocked {tool_name}: {result.admissibility} — "
                    f"{result.decision.get('decision_reason', '')}"
                )
            if result.admissibility == "draft_only":
                spec = self.registry.resolve(tool_name)
                if spec.mutates_state:
                    raise PermissionError(f"AKTA draft_only: mutating tool {tool_name} not permitted")
            return tool_fn(*args, **kwargs)

        return gated
