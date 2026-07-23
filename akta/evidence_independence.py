"""Evidence independence invariants (AKTA 1.1 WS9).

SCOPE grants may satisfy human_review / authorization requirements.
They must never satisfy empirical evidence, convert weak evidence into strong
evidence, erase evidence-based blocks, or override deployment-profile /
domain-overlay / unknown-tool / unsupported-autonomous blocks.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from akta.grant_override import (
    GRANT_SATISFIABLE_LAYERS,
    compute_grant_layer_satisfaction,
    grant_may_satisfy_evidence,
)

# Decision provenance layers recorded on every grant-aware decision.
DECISION_PROVENANCE_LAYERS = (
    "evidence",
    "deployment_profile",
    "domain_overlay",
    "authorization",
    "tool",
    "final",
)

# Outcomes a SCOPE grant must never upgrade away from.
PROTECTED_BLOCK_DECISIONS = frozenset(
    {
        "blocked",
        "abstain_insufficient_context",
        "review_required",
    }
)

PROTECTED_BLOCK_REASONS = frozenset(
    {
        "evidence",
        "evidence_block",
        "abstain_missing_evidence",
        "deployment_profile",
        "deployment-profile",
        "domain_overlay",
        "domain-overlay",
        "unknown_consequential_tool",
        "unknown_tool",
        "unsupported_autonomous_profile",
        "unsupported_profile",
    }
)


@dataclass(frozen=True)
class LayerProvenance:
    """One layer of the composed Decision provenance stack."""

    layer: str
    decision: str | None
    reason: str | None = None
    satisfied_by_grant: bool = False
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DecisionLayerProvenance:
    """Layered Decision provenance for evidence-independent composition."""

    evidence: LayerProvenance
    deployment_profile: LayerProvenance
    domain_overlay: LayerProvenance
    authorization: LayerProvenance
    tool: LayerProvenance
    final: LayerProvenance
    evidence_never_satisfied_by_grant: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence": self.evidence.to_dict(),
            "deployment_profile": self.deployment_profile.to_dict(),
            "domain_overlay": self.domain_overlay.to_dict(),
            "authorization": self.authorization.to_dict(),
            "tool": self.tool.to_dict(),
            "final": self.final.to_dict(),
            "evidence_never_satisfied_by_grant": self.evidence_never_satisfied_by_grant,
        }


@dataclass
class EvidenceIndependenceResult:
    ok: bool
    violations: list[str] = field(default_factory=list)
    layers: DecisionLayerProvenance | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "violations": list(self.violations),
            "layers": self.layers.to_dict() if self.layers else None,
        }


def assert_grant_cannot_satisfy_evidence() -> None:
    """Hard invariant: grant_may_satisfy_evidence is always False."""
    if grant_may_satisfy_evidence():
        raise AssertionError("SCOPE grant must never satisfy the evidence layer")


def _layer_mentions_evidence(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "evidence",
            "e1_",
            "e2_",
            "e3_",
            "insufficient evidence",
            "missing evidence",
        )
    )


def _is_evidence_block(decision: str | None, reason: str | None, source: str | None) -> bool:
    if decision in ("blocked", "abstain_insufficient_context") and _layer_mentions_evidence(
        reason
    ):
        return True
    if source and "evidence" in source.lower():
        return True
    if reason:
        for token in PROTECTED_BLOCK_REASONS:
            if token.replace("-", "_") in reason.lower().replace("-", "_"):
                if "evidence" in token or "evidence" in reason.lower():
                    return True
    return False


def grant_must_not_upgrade_block(
    *,
    pre_grant_decision: str | None,
    post_grant_decision: str | None,
    pre_grant_reason: str | None = None,
    block_kind: str,
) -> str | None:
    """Return violation message when a grant upgrades a protected block to allowed."""
    if pre_grant_decision not in PROTECTED_BLOCK_DECISIONS:
        return None
    if post_grant_decision in (
        "allowed",
        "allowed_with_logging",
        "draft_only",
    ):
        return (
            f"SCOPE grant must not upgrade {block_kind} decision "
            f"{pre_grant_decision!r} to {post_grant_decision!r}"
        )
    if block_kind in {"evidence", "abstain_missing_evidence"} and _is_evidence_block(
        pre_grant_decision, pre_grant_reason, None
    ):
        if post_grant_decision != pre_grant_decision and post_grant_decision in (
            "allowed",
            "allowed_with_logging",
            "draft_only",
        ):
            return "SCOPE grant must not clear an evidence-based block"
    return None


def build_decision_layer_provenance(
    *,
    evidence_decision: str | None = None,
    evidence_reason: str | None = None,
    deployment_profile_decision: str | None = None,
    deployment_profile_reason: str | None = None,
    domain_overlay_decision: str | None = None,
    domain_overlay_reason: str | None = None,
    authorization_decision: str | None = None,
    authorization_reason: str | None = None,
    tool_decision: str | None = None,
    tool_reason: str | None = None,
    final_decision: str | None = None,
    final_reason: str | None = None,
    scope_grant: dict[str, Any] | None = None,
    authorization_satisfied_by_grant: bool = False,
) -> DecisionLayerProvenance:
    """Assemble layered Decision provenance; evidence never satisfied by grant."""
    assert_grant_cannot_satisfy_evidence()
    auth_by_grant = bool(authorization_satisfied_by_grant and scope_grant is not None)
    return DecisionLayerProvenance(
        evidence=LayerProvenance(
            layer="evidence",
            decision=evidence_decision,
            reason=evidence_reason,
            satisfied_by_grant=False,
            source="evidence_rules",
        ),
        deployment_profile=LayerProvenance(
            layer="deployment_profile",
            decision=deployment_profile_decision,
            reason=deployment_profile_reason,
            satisfied_by_grant=False,
            source="deployment_profiles",
        ),
        domain_overlay=LayerProvenance(
            layer="domain_overlay",
            decision=domain_overlay_decision,
            reason=domain_overlay_reason,
            satisfied_by_grant=False,
            source="domain_overlay",
        ),
        authorization=LayerProvenance(
            layer="authorization",
            decision=authorization_decision,
            reason=authorization_reason,
            satisfied_by_grant=auth_by_grant,
            source="scope_grant" if auth_by_grant else "authorization",
        ),
        tool=LayerProvenance(
            layer="tool",
            decision=tool_decision,
            reason=tool_reason,
            satisfied_by_grant=False,
            source="tool_registry",
        ),
        final=LayerProvenance(
            layer="final",
            decision=final_decision,
            reason=final_reason,
            satisfied_by_grant=False,
            source="composed",
        ),
        evidence_never_satisfied_by_grant=True,
    )


def check_evidence_independence(
    *,
    scope_grant: dict[str, Any] | None,
    pre_layers: dict[str, dict[str, Any]] | None = None,
    post_decision: str | None = None,
    post_reason: str | None = None,
    final_layers: DecisionLayerProvenance | None = None,
) -> EvidenceIndependenceResult:
    """Verify a signed/valid grant cannot erase protected admissibility layers."""
    violations: list[str] = []
    assert_grant_cannot_satisfy_evidence()

    if scope_grant is not None:
        satisfaction = compute_grant_layer_satisfaction(scope_grant)
        for layer in satisfaction.get("satisfied_layers") or []:
            name = layer.get("layer")
            if name not in GRANT_SATISFIABLE_LAYERS:
                violations.append(
                    f"grant must not satisfy non-authorization layer {name!r}"
                )
            if name == "evidence":
                violations.append("grant must never list evidence under satisfied_layers")
        if not satisfaction.get("evidence_never_satisfied_by_grant", False):
            violations.append("evidence_never_satisfied_by_grant must be True")

    pre = pre_layers or {}
    for kind in (
        "evidence",
        "abstain_missing_evidence",
        "deployment_profile",
        "domain_overlay",
        "unknown_consequential_tool",
        "unsupported_autonomous_profile",
    ):
        layer = pre.get(kind) or {}
        pre_decision = layer.get("decision")
        violation = grant_must_not_upgrade_block(
            pre_grant_decision=pre_decision,
            post_grant_decision=post_decision,
            pre_grant_reason=layer.get("reason"),
            block_kind=kind,
        )
        if violation:
            violations.append(violation)

    layers = final_layers
    if layers is None and scope_grant is not None:
        layers = build_decision_layer_provenance(
            evidence_decision=(pre.get("evidence") or {}).get("decision"),
            evidence_reason=(pre.get("evidence") or {}).get("reason"),
            deployment_profile_decision=(pre.get("deployment_profile") or {}).get(
                "decision"
            ),
            domain_overlay_decision=(pre.get("domain_overlay") or {}).get("decision"),
            authorization_decision="authorization_satisfied"
            if scope_grant
            else None,
            tool_decision=(pre.get("unknown_consequential_tool") or {}).get("decision"),
            final_decision=post_decision,
            final_reason=post_reason,
            scope_grant=scope_grant,
            authorization_satisfied_by_grant=True,
        )
    if layers is not None and layers.evidence.satisfied_by_grant:
        violations.append("evidence layer marked satisfied_by_grant")
    if layers is not None and not layers.evidence_never_satisfied_by_grant:
        violations.append("layered provenance missing evidence_never_satisfied_by_grant")

    return EvidenceIndependenceResult(
        ok=not violations, violations=violations, layers=layers
    )


def attach_layer_provenance_to_decision(
    decision: dict[str, Any],
    provenance: DecisionLayerProvenance,
) -> dict[str, Any]:
    """Record layered provenance on a Decision dict (non-destructive copy)."""
    out = dict(decision)
    out["decision_layer_provenance"] = provenance.to_dict()
    # Preserve legacy grant_layer_satisfaction shape when present.
    satisfaction = dict(out.get("grant_layer_satisfaction") or {})
    satisfaction["evidence_never_satisfied_by_grant"] = True
    satisfaction["decision_layers"] = {
        name: provenance.to_dict()[name]
        for name in (
            "evidence",
            "deployment_profile",
            "domain_overlay",
            "authorization",
            "tool",
            "final",
        )
    }
    out["grant_layer_satisfaction"] = satisfaction
    return out
