"""AKTA Gate — primary runtime decision engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from akta.classify import (
    classify,
    resolve_evidence_state,
    resolve_validation_status,
    resolve_verification_status,
)
from akta.consequentiality import classify_consequentiality
from akta.context import AKTAContext
from akta.evaluate import evaluate_admissibility
from akta.overlays import DomainOverlay
from akta.policy import PolicyBundle
from akta.records import (
    AKTADecision,
    build_review_trigger,
    new_decision_id,
    utc_now_iso,
    validate_against_schema,
)
from akta.tool_registry import ToolRegistry


class AKTAGate:
    """Scientific action admissibility gate."""

    def __init__(
        self,
        policy: PolicyBundle,
        overlays_dir: str | Path | None = None,
    ) -> None:
        self.policy = policy
        self.tool_registry = ToolRegistry(policy.tool_registry)
        self.overlays_dir = Path(overlays_dir or "overlays")

    @classmethod
    def from_policy_dir(
        cls,
        policy_dir: str | Path = "policy/",
        overlays_dir: str | Path | None = None,
        tool_registry_path: str | Path | None = None,
    ) -> AKTAGate:
        policy = PolicyBundle.from_dir(policy_dir, tool_registry_path=tool_registry_path)
        return cls(policy, overlays_dir=overlays_dir)

    def evaluate(
        self,
        ai_output: Any,
        requested_tool: str,
        requested_action: str,
        context: AKTAContext | dict[str, Any] | None = None,
        deployment_profile: str = "P2_analysis_assistant",
        domain_overlay: str | None = None,
        validate_output: bool = True,
    ) -> AKTADecision:
        ctx = context if isinstance(context, AKTAContext) else AKTAContext.from_dict(context or {})
        self.policy.get_profile(deployment_profile)

        overlay_obj: DomainOverlay | None = None
        if domain_overlay:
            overlay_obj = DomainOverlay.load(domain_overlay, self.overlays_dir)

        tool_spec = self.tool_registry.resolve(requested_tool)
        classification = classify(
            self.policy,
            requested_tool,
            requested_action,
            tool_spec,
            ctx,
            ai_output=ai_output,
        )

        evidence_state = resolve_evidence_state(ctx)
        validation_status = resolve_validation_status(ctx)
        verification_status = resolve_verification_status(ctx)

        consequentiality = classify_consequentiality(
            classification.action_type,
            tool_spec,
            requested_tool,
            requested_action,
            ai_output,
            ctx,
            overlay_obj,
        )

        evaluation = evaluate_admissibility(
            policy=self.policy,
            profile=deployment_profile,
            action_type=classification.action_type,
            evidence_state=evidence_state,
            tool_spec=tool_spec,
            requested_tool=requested_tool,
            context=ctx,
            overlay=overlay_obj,
            consequentiality=consequentiality,
            classifier_confidence=classification.confidence,
            ai_output=ai_output,
            requested_action=requested_action,
        )

        decision_id = new_decision_id()
        record_id = f"AKTA-SAR-PENDING-{decision_id.split('-')[-1]}"
        review_trigger = None
        if evaluation.review_required or evaluation.authorization_required:
            review_trigger = build_review_trigger(
                decision_id=decision_id,
                record_id=record_id,
                role=evaluation.required_review_role or "domain_scientist",
                action_type=classification.action_type,
                requested_tool=requested_tool,
                requested_action=requested_action,
                deployment_profile=deployment_profile,
                scientific_action_type=classification.action_type,
                responsibility_level=classification.responsibility_level,
                evidence_state=evidence_state,
                validation_status=validation_status,
                verification_status=verification_status,
                admissibility=evaluation.admissibility,
                decision_reason=evaluation.decision_reason,
                blocked_tools=evaluation.blocked_tools,
                allowed_next_steps=evaluation.next_admissible_steps,
                policy_hash=self.policy.policy_hash,
                tool_registry_hash=self.policy.tool_registry_hash,
                domain_overlay_hash=overlay_obj.overlay_hash if overlay_obj else None,
                classifier_confidence=classification.confidence,
                classification_rationale=classification.rationale,
                consequentiality=evaluation.consequentiality,
                consequentiality_reason=evaluation.consequentiality_reason,
                scientific_context={
                    "domain": ctx.domain or (overlay_obj.domain if overlay_obj else "generic"),
                    "project_id": ctx.project_id,
                    "system_id": ctx.system_id,
                },
                scope_config=self.policy.tool_to_requested_scope,
                overlay=overlay_obj,
            )
            if validate_output:
                validate_against_schema(review_trigger, "review_trigger.schema.json")

        decision_data: dict[str, Any] = {
            "decision_id": decision_id,
            "timestamp": utc_now_iso(),
            "system_id": ctx.system_id,
            "deployment_profile": deployment_profile,
            "domain": ctx.domain or (overlay_obj.domain if overlay_obj else "generic"),
            "requested_action": requested_action,
            "requested_tool": requested_tool,
            "scientific_action_type": classification.action_type,
            "responsibility_level": classification.responsibility_level,
            "evidence_state": evidence_state,
            "validation_status": validation_status,
            "verification_status": verification_status,
            "admissibility": evaluation.admissibility,
            "decision_reason": evaluation.decision_reason,
            "required_review_role": evaluation.required_review_role,
            "blocked_tools": evaluation.blocked_tools,
            "allowed_tools": evaluation.allowed_tools,
            "next_admissible_steps": evaluation.next_admissible_steps,
            "record_required": evaluation.record_required,
            "review_required": evaluation.review_required,
            "authorization_required": evaluation.authorization_required,
            "consequentiality": evaluation.consequentiality,
            "consequentiality_reason": evaluation.consequentiality_reason,
            "policy_version": self.policy.version,
            "policy_hash": self.policy.policy_hash,
            "policy_file_versions": dict(self.policy.policy_file_versions),
            "domain_overlay_version": overlay_obj.version if overlay_obj else None,
            "domain_overlay_hash": overlay_obj.overlay_hash if overlay_obj else None,
            "tool_registry_hash": self.policy.tool_registry_hash,
            "classifier_confidence": classification.confidence,
            "classification_rationale": classification.rationale,
            "classification": {
                "primary_action_type": classification.primary_action_type,
                "alternate_action_types": classification.alternate_action_types,
                "matched_source": classification.matched_source,
                "matched_evidence": classification.matched_evidence,
                "uncertainty_flags": classification.uncertainty_flags,
                "classifier_mode": classification.classifier_mode,
            },
            "llm_advisory": classification.llm_metadata,
            "ai_output_summary": (
                ai_output if isinstance(ai_output, str)
                else (ai_output.get("summary") if isinstance(ai_output, dict) else str(ai_output))
            ),
        }

        if review_trigger:
            decision_data["review_trigger"] = review_trigger

        decision = AKTADecision(decision_data)
        if validate_output:
            validate_against_schema(decision.to_dict(), "akta_decision.schema.json")
        return decision
