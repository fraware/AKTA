"""AKTA Gate — primary runtime decision engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from akta.bindings import build_binding_set, verify_policy_hashes
from akta.classify import (
    classify,
    resolve_evidence_state,
    resolve_validation_status,
    resolve_verification_status,
)
from akta.consequentiality import classify_consequentiality
from akta.context import AKTAContext
from akta.errors import AKTAError
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
        *,
        verify_effective_policy: bool | None = None,
    ) -> AKTAGate:
        """Load policy bundle. Recomputes effective-policy provenance (P0-G).

        When ``verify_effective_policy`` is True (or production/signed mode),
        rejects stale/tampered policy inputs vs stored effective_policy_manifest.
        """
        import os

        from akta.effective_policy import require_effective_policy_integrity
        from akta.policy_integrity import is_production_mode, require_signed_policy

        policy = PolicyBundle.from_dir(policy_dir, tool_registry_path=tool_registry_path)
        if verify_effective_policy is None:
            verify_effective_policy = (
                is_production_mode()
                or require_signed_policy()
                or os.environ.get("AKTA_VERIFY_EFFECTIVE_POLICY", "").lower()
                in ("1", "true", "yes")
            )
        if verify_effective_policy:
            require_effective_policy_integrity(
                policy_dir,
                overlays_dir=overlays_dir,
                integrity_mode=getattr(policy, "integrity_mode", "dev_unsigned"),
            )
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
        pilot_mode: str | None = None,
    ) -> AKTADecision:
        raw_ctx = context.to_dict() if isinstance(context, AKTAContext) else dict(context or {})
        # Prefer normalized vsa_bundle; fail closed on digest/ambiguity when VSA present.
        if raw_ctx.get("vsa_bundle") or raw_ctx.get("vsa_report") or raw_ctx.get("evidence_refs"):
            from adapters.vsa.import_report import VSAImportError, resolve_vsa_source

            try:
                resolved = resolve_vsa_source(raw_ctx)
                if raw_ctx.get("vsa_bundle") is None:
                    raw_ctx["vsa_bundle"] = resolved
            except VSAImportError:
                # Ambiguous/multi-ref or missing digestable source — fail closed.
                raise
        ctx = AKTAContext.from_dict(raw_ctx)
        self.policy.get_profile(deployment_profile)

        # AS-05: pilot mode enforcement before tool-resolution side effects.
        mode_meta: dict[str, Any] = {}
        if pilot_mode is not None or raw_ctx.get("pilot_mode") or raw_ctx.get("metadata", {}).get("pilot_mode"):
            from akta.pilot_workflow import apply_pilot_mode_to_evaluation, resolve_pilot_mode

            explicit = pilot_mode or raw_ctx.get("pilot_mode") or (raw_ctx.get("metadata") or {}).get(
                "pilot_mode"
            )
            mode = resolve_pilot_mode(explicit if isinstance(explicit, str) else None)
            mode_meta = apply_pilot_mode_to_evaluation(
                mode=mode,
                requested_tool=requested_tool,
                tool_spec=None,
                context=raw_ctx,
            )
            # Hard blocks force blocked decisions below; do not abort before evaluate
            # (shadow/retrospective still produce reconstructable decision artifacts).

        overlay_obj: DomainOverlay | None = None
        if domain_overlay:
            overlay_obj = DomainOverlay.load(domain_overlay, self.overlays_dir)

        tool_spec = self.tool_registry.resolve(requested_tool)
        if mode_meta:
            from akta.pilot_workflow import enforce_tool_for_mode, resolve_pilot_mode

            explicit = pilot_mode or raw_ctx.get("pilot_mode") or (raw_ctx.get("metadata") or {}).get(
                "pilot_mode"
            )
            mode = resolve_pilot_mode(explicit if isinstance(explicit, str) else None)
            tool_block = enforce_tool_for_mode(mode, requested_tool=requested_tool, tool_spec=tool_spec)
            if tool_block:
                mode_meta = {**mode_meta, **tool_block}
            if mode_meta.get("hard_block"):
                meta = dict(ctx.metadata or {})
                meta["pilot_mode_block"] = mode_meta.get("block_reason")
                meta["pilot_mode"] = mode.value
                ctx.metadata = meta

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
            review_trigger["bindings"] = {
                "decision_id": decision_id,
                "record_id": record_id,
                "policy_hash": self.policy.policy_hash,
                "tool_registry_hash": self.policy.tool_registry_hash,
            }
            # Recompute hash after binding attachment (AS-06).
            from akta.hash import hash_object

            review_trigger["review_trigger_hash"] = hash_object(
                {k: v for k, v in review_trigger.items() if k != "review_trigger_hash"}
            )
            if validate_output:
                validate_against_schema(review_trigger, "review_trigger.schema.json")

        evaluation_layers = [
            {
                "source": layer.source,
                "decision": layer.decision,
                "reason": layer.reason,
            }
            for layer in evaluation.layers
        ]
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
            "evaluation_layers": evaluation_layers,
            "policy_version": self.policy.version,
            "policy_hash": self.policy.policy_hash,
            "policy_file_versions": dict(self.policy.policy_file_versions),
            "policy_integrity_mode": self.policy.integrity_mode,
            "policy": self.policy.policy_binding(),
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

        # AS-01 bindings
        vsa_bundle = ctx.vsa_bundle or (
            {"schema": "legacy-vsa-report", **ctx.vsa_report} if ctx.vsa_report else None
        )
        scientific_question = raw_ctx.get("scientific_question") or (
            (ctx.vsa_report or {}).get("scientific_question") if ctx.vsa_report else None
        )
        proposed_action = {
            "requested_tool": requested_tool,
            "requested_action": requested_action,
            "scientific_action_type": classification.action_type,
        }
        bindings = build_binding_set(
            decision_id=decision_id,
            record_id=record_id,
            policy_hash=self.policy.policy_hash,
            tool_registry_hash=self.policy.tool_registry_hash,
            requested_tool=requested_tool,
            action_class=classification.action_type,
            domain_overlay_hash=overlay_obj.overlay_hash if overlay_obj else None,
            scientific_question=scientific_question,
            proposed_action=proposed_action,
            vsa_bundle=vsa_bundle,
            scope_review_ref=(review_trigger or {}).get("review_trigger_id"),
            validate=validate_output,
        )
        decision_data["bindings"] = bindings

        # Stale hash check when caller declares expected hashes in context.
        declared = raw_ctx.get("declared_policy_hashes") or (raw_ctx.get("metadata") or {}).get(
            "declared_policy_hashes"
        )
        if isinstance(declared, dict):
            stale = verify_policy_hashes(
                bindings={
                    "policy_hash": declared.get("policy_hash", bindings["policy_hash"]),
                    "tool_registry_hash": declared.get(
                        "tool_registry_hash", bindings["tool_registry_hash"]
                    ),
                    "domain_overlay_hash": declared.get("domain_overlay_hash"),
                },
                loaded_policy_hash=self.policy.policy_hash,
                loaded_overlay_hash=overlay_obj.overlay_hash if overlay_obj else None,
                loaded_tool_registry_hash=self.policy.tool_registry_hash,
            )
            if stale:
                raise AKTAError("; ".join(stale))

        # AS-03 decision basis (attached when builder available)
        try:
            from akta.decision_basis import build_decision_basis
            from akta.hash import hash_object

            basis = build_decision_basis(
                evaluation_layers=evaluation_layers,
                evidence_state=evidence_state,
                admissibility=evaluation.admissibility,
                decision_reason=evaluation.decision_reason,
                next_admissible_steps=evaluation.next_admissible_steps,
                required_review_role=evaluation.required_review_role,
                action_class=classification.action_type,
                tool_spec=tool_spec,
                policy=self.policy,
                overlay=overlay_obj,
                context=raw_ctx,
            )
            decision_data["decision_basis"] = basis
            decision_data["bindings"]["decision_basis_digest"] = hash_object(basis)
        except ImportError:
            pass

        # AS-04 uniform failures
        try:
            from akta.failure_mapping import failures_for_decision

            fails = failures_for_decision(decision_data)
            if fails:
                decision_data["failure"] = fails[0]
                decision_data["failures"] = fails
        except ImportError:
            pass

        # AS-05 pilot mode fields
        if mode_meta:
            decision_data["pilot_mode"] = mode_meta.get("pilot_mode")
            decision_data["shadow"] = bool(mode_meta.get("shadow"))
            decision_data["operational_influence"] = bool(
                mode_meta.get("operational_influence", False)
            )
            if mode_meta.get("hard_block") or (ctx.metadata or {}).get("pilot_mode_block"):
                decision_data["admissibility"] = "blocked"
                decision_data["decision_reason"] = (
                    mode_meta.get("block_reason")
                    or (ctx.metadata or {}).get("pilot_mode_block")
                    or decision_data["decision_reason"]
                )
                decision_data["blocked_tools"] = sorted(
                    set(decision_data.get("blocked_tools") or []) | {requested_tool}
                )
                try:
                    from akta.failure_mapping import map_local_reason

                    decision_data["failure"] = map_local_reason(
                        "pilot_mode_restriction",
                        detail=decision_data["decision_reason"],
                        layer="pilot_mode",
                    )
                    decision_data["failures"] = [decision_data["failure"]]
                except ImportError:
                    pass

        decision = AKTADecision(decision_data)
        if validate_output:
            validate_against_schema(decision.to_dict(), "akta_decision.schema.json")
        return decision

    def evaluate_with_grant(
        self,
        ai_output: Any,
        requested_tool: str,
        requested_action: str,
        context: AKTAContext | dict[str, Any] | None = None,
        deployment_profile: str = "P2_analysis_assistant",
        domain_overlay: str | None = None,
        scope_grant: dict[str, Any] | None = None,
        review_decision: dict[str, Any] | None = None,
        record: dict[str, Any] | None = None,
        trigger: dict[str, Any] | None = None,
        validate_output: bool = True,
        verification_mode: str | None = None,
        require_capability_envelope: bool | None = None,
        trust_store: dict[str, Any] | None = None,
        ledger_status: dict[str, Any] | None = None,
        authorization_manifest: dict[str, Any] | None = None,
        source_artifacts: dict[str, Any] | None = None,
        action_class: str | None = None,
        status_trust_store: dict[str, Any] | None = None,
        manifest_trust_store: dict[str, Any] | None = None,
    ) -> AKTADecision:
        """Re-gate after SCOPE grant or review decision with expiry enforcement (F14).

        Grant verification runs before metadata apply. In pilot/release/production
        modes, missing allowed_tools or simulated grants fail closed.
        """
        from akta.review_decision import (
            apply_review_decision_to_context,
            enforce_grant_expiry,
        )
        from akta.review_loop import apply_grant_decision_constraints, prepare_grant_context
        from akta.evidence_independence import (
            attach_layer_provenance_to_decision,
            build_decision_layer_provenance,
            check_evidence_independence,
            extract_layer_snapshots,
            provenance_objects_for_authorization,
        )

        ctx_dict: dict[str, Any]
        if isinstance(context, AKTAContext):
            ctx_dict = context.to_dict()
        else:
            ctx_dict = dict(context or {})

        # Capture pre-grant admissibility from prior record/decision when present.
        pre_grant_adm = None
        if isinstance(record, dict):
            pre_grant_adm = (record.get("decision") or {}).get("admissibility")
        if pre_grant_adm:
            meta0 = dict(ctx_dict.get("metadata") or {})
            meta0.setdefault("pre_grant_admissibility", pre_grant_adm)
            meta0.setdefault("initial_admissibility", pre_grant_adm)
            ctx_dict["metadata"] = meta0

        grant_state: Any = None
        if review_decision is not None:
            ctx_dict = apply_review_decision_to_context(ctx_dict, review_decision)
        elif scope_grant is not None:
            grant_state = prepare_grant_context(
                ctx_dict,
                scope_grant=scope_grant,
                record=record,
                trigger=trigger,
                deployment_profile=deployment_profile,
                verification_mode=verification_mode,
                require_capability_envelope=require_capability_envelope,
                trust_store=trust_store,
                ledger_status=ledger_status,
                authorization_manifest=authorization_manifest,
                source_artifacts=source_artifacts,
                requested_tool=requested_tool,
                requested_action=requested_action,
                action_class=action_class,
                status_trust_store=status_trust_store,
                manifest_trust_store=manifest_trust_store,
            )
            ctx_dict = grant_state.context

        ctx_dict = enforce_grant_expiry(ctx_dict)
        decision = self.evaluate(
            ai_output=ai_output,
            requested_tool=requested_tool,
            requested_action=requested_action,
            context=AKTAContext.from_dict(ctx_dict),
            deployment_profile=deployment_profile,
            domain_overlay=domain_overlay,
            validate_output=validate_output,
        )

        if grant_state is not None:
            updated = apply_grant_decision_constraints(
                decision.to_dict(),
                grant_state,
                requested_tool=requested_tool,
            )
            # P0-11: layered Decision provenance + evidence independence check.
            # Distinct layer objects — never feed final composition into evidence_layer.
            data = dict(updated)
            eval_layers = data.get("evaluation_layers") or []
            snapshots = extract_layer_snapshots(eval_layers)
            pre_layers = {
                "evidence": snapshots["evidence"],
                "deployment_profile": snapshots["deployment_profile"],
                "domain_overlay": snapshots["domain_overlay"],
                "unknown_consequential_tool": snapshots["tool"],
            }
            # Prefer pre-grant evidence snapshot when recorded on the prior path.
            meta = (grant_state.context or {}).get("metadata") or {}
            if meta.get("pre_grant_evidence_decision"):
                pre_layers["evidence"] = {
                    "decision": meta.get("pre_grant_evidence_decision"),
                    "reason": meta.get("pre_grant_evidence_reason"),
                    "source": "evidence_rules",
                }
            provenance = build_decision_layer_provenance(
                evaluation_layers=eval_layers,
                evidence_decision=(pre_layers.get("evidence") or {}).get("decision"),
                evidence_reason=(pre_layers.get("evidence") or {}).get("reason"),
                deployment_profile_decision=(
                    (pre_layers.get("deployment_profile") or {}).get("decision")
                ),
                deployment_profile_reason=(
                    (pre_layers.get("deployment_profile") or {}).get("reason")
                ),
                domain_overlay_decision=(
                    (pre_layers.get("domain_overlay") or {}).get("decision")
                ),
                domain_overlay_reason=(
                    (pre_layers.get("domain_overlay") or {}).get("reason")
                ),
                authorization_decision="authorization_satisfied",
                tool_decision=(pre_layers.get("unknown_consequential_tool") or {}).get(
                    "decision"
                ),
                tool_reason=(pre_layers.get("unknown_consequential_tool") or {}).get(
                    "reason"
                ),
                final_decision=data.get("admissibility"),
                final_reason=data.get("decision_reason") or data.get("reason"),
                scope_grant=scope_grant,
                authorization_satisfied_by_grant=True,
            )
            independence = check_evidence_independence(
                scope_grant=scope_grant,
                pre_layers=pre_layers,
                post_decision=data.get("admissibility"),
                post_reason=data.get("decision_reason") or data.get("reason"),
                final_layers=provenance,
            )
            data = attach_layer_provenance_to_decision(data, provenance)
            data["evidence_independence"] = independence.to_dict()
            if meta.get("pre_grant_admissibility"):
                auth = dict(data.get("authorization_provenance") or {})
                auth["initial_admissibility"] = meta["pre_grant_admissibility"]
                data["authorization_provenance"] = auth
            if data.get("authorization_provenance") is not None:
                # Distinct layer objects — not the independence composition blob.
                data["authorization_provenance"].update(
                    provenance_objects_for_authorization(provenance)
                )
                data["authorization_provenance"]["decision_layer_provenance"] = (
                    provenance.to_dict()
                )
                data["authorization_provenance"]["evidence_independence"] = (
                    independence.to_dict()
                )
                data["authorization_provenance"]["final_decision"] = data.get(
                    "admissibility"
                )
            decision = AKTADecision(data)
            if validate_output:
                validate_against_schema(decision.to_dict(), "akta_decision.schema.json")

        return decision
