"""LangGraph-style middleware for AKTA pre-action gating (v0.6 SCOPE closed-loop)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from akta.context import AKTAContext
from akta.errors import AKTAReviewRequired
from akta.gate import AKTAGate
from akta.review_decision import enforce_grant_expiry, is_review_expired
from akta.session_grant_store import SessionGrantStore
from akta.tool_registry import ToolRegistry


@dataclass
class GateResult:
    """Structured gate outcome for LangGraph integration."""

    admissibility: str
    allowed: bool
    decision: dict[str, Any]
    review_trigger: dict[str, Any] | None = None
    grant_invalidated: bool = False
    scope_handoff_required: bool = False


@dataclass
class MiddlewareState:
    """Track active SCOPE grant for scoped retry."""

    scope_grant: dict[str, Any] | None = None
    review_decision: dict[str, Any] | None = None
    invalidated: bool = False


class AKTALangGraphMiddleware:
    """Intercept tool calls and gate through AKTA before execution."""

    def __init__(
        self,
        policy_dir: str = "policy",
        overlays_dir: str = "overlays",
        deployment_profile: str = "P2_analysis_assistant",
        domain_overlay: str | None = None,
        scope_handoff: bool = True,
    ) -> None:
        self.gate = AKTAGate.from_policy_dir(policy_dir, overlays_dir=overlays_dir)
        self.registry = ToolRegistry(self.gate.policy.tool_registry)
        self.deployment_profile = deployment_profile
        self.domain_overlay = domain_overlay
        self.scope_handoff = scope_handoff
        self.state = MiddlewareState()
        self.grant_store = SessionGrantStore()
        self._session_id = "default"

    def invalidate_grant(self) -> None:
        """Invalidate active grant (e.g. on expiry)."""
        self.state.invalidated = True
        self.state.scope_grant = None

    def reset_state(self) -> None:
        """Clear session grant state for a new agent turn."""
        self.state = MiddlewareState()
        self.grant_store.clear(self._session_id)

    def apply_scope_grant(self, scope_grant: dict[str, Any]) -> None:
        """Store SCOPE grant for scoped retry."""
        self.state.scope_grant = scope_grant
        self.state.invalidated = False
        self.grant_store.put(
            self._session_id,
            scope_grant,
            bound_evidence_state=(scope_grant.get("bound_evidence_state")),
        )

    def _check_grant_expiry(self, context: dict[str, Any]) -> dict[str, Any]:
        ctx = enforce_grant_expiry(context)
        metadata = ctx.get("metadata") or {}
        expires_at = metadata.get("prior_review_expires_at")
        if expires_at and is_review_expired(expires_at):
            self.invalidate_grant()
        return ctx

    def evaluate_tool(
        self,
        tool_name: str,
        action_name: str,
        *,
        ai_output: Any = "",
        context: dict[str, Any] | None = None,
    ) -> GateResult:
        ctx = dict(context or {})
        grant_invalidated = False

        if self.state.scope_grant and not self.state.invalidated:
            decision = self.gate.evaluate_with_grant(
                ai_output=ai_output,
                requested_tool=tool_name,
                requested_action=action_name,
                context=AKTAContext.from_dict(ctx),
                deployment_profile=self.deployment_profile,
                domain_overlay=self.domain_overlay,
                scope_grant=self.state.scope_grant,
            )
        else:
            ctx = self._check_grant_expiry(ctx)
            if self.state.invalidated:
                grant_invalidated = True
                metadata = dict(ctx.get("metadata") or {})
                metadata["prior_review_expired"] = True
                ctx["metadata"] = metadata

            decision = self.gate.evaluate(
                ai_output=ai_output,
                requested_tool=tool_name,
                requested_action=action_name,
                context=AKTAContext.from_dict(ctx),
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

        scope_handoff_required = adm == "review_required" and self.scope_handoff

        return GateResult(
            admissibility=adm,
            allowed=allowed,
            decision=d,
            review_trigger=d.get("review_trigger"),
            grant_invalidated=grant_invalidated,
            scope_handoff_required=scope_handoff_required,
        )

    def retry_with_grant(
        self,
        scope_grant: dict[str, Any],
        tool_name: str,
        action_name: str,
        *,
        ai_output: Any = "",
        context: dict[str, Any] | None = None,
    ) -> GateResult:
        """Scoped retry after SCOPE grant issuance."""
        self.apply_scope_grant(scope_grant)
        return self.evaluate_tool(
            tool_name, action_name, ai_output=ai_output, context=context
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
            if result.grant_invalidated:
                raise PermissionError(
                    f"AKTA grant expired for {tool_name}; re-submit SCOPE review"
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
