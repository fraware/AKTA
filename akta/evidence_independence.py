"""Evidence independence invariants (AKTA 1.2 P0-11).

SCOPE grants may satisfy human_review / authorization requirements.
They must never satisfy empirical evidence, convert weak evidence into strong
evidence, erase evidence-based blocks, or override deployment-profile /
domain-overlay / unknown-tool / unsupported-autonomous blocks.

Decision-layer provenance is recorded as distinct objects. The final composed
admissibility must never be written back into ``evidence_layer``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

from akta.grant_override import (
    GRANT_SATISFIABLE_LAYERS,
    compute_grant_layer_satisfaction,
    grant_may_satisfy_evidence,
)

# Decision provenance layers recorded on every grant-aware decision (plan names).
DECISION_PROVENANCE_LAYERS = (
    "evidence_layer",
    "deployment_profile_layer",
    "domain_overlay_layer",
    "authorization_layer",
    "tool_layer",
    "final_composition",
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

_EVIDENCE_SOURCES = frozenset({"evidence_rules", "evidence"})
_PROFILE_SOURCES = frozenset({"deployment_profile"})
_OVERLAY_SOURCES = frozenset(
    {"domain_overlay", "domain_overlay_tool", "domain_overlay_hazard"}
)
_TOOL_SOURCES = frozenset(
    {"tool_registry", "mandatory_tool_declaration", "unknown_consequential_tool"}
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
    """Layered Decision provenance for evidence-independent composition.

    Field names match the 1.2 plan: evidence_layer through final_composition.
    ``final_composition`` is the composed outcome and must not be copied into
    ``evidence_layer``.
    """

    evidence_layer: LayerProvenance
    deployment_profile_layer: LayerProvenance
    domain_overlay_layer: LayerProvenance
    authorization_layer: LayerProvenance
    tool_layer: LayerProvenance
    final_composition: LayerProvenance
    evidence_never_satisfied_by_grant: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_layer": self.evidence_layer.to_dict(),
            "deployment_profile_layer": self.deployment_profile_layer.to_dict(),
            "domain_overlay_layer": self.domain_overlay_layer.to_dict(),
            "authorization_layer": self.authorization_layer.to_dict(),
            "tool_layer": self.tool_layer.to_dict(),
            "final_composition": self.final_composition.to_dict(),
            "evidence_never_satisfied_by_grant": self.evidence_never_satisfied_by_grant,
        }

    # Legacy short-name accessors (pre-1.2 callers / tests).
    @property
    def evidence(self) -> LayerProvenance:
        return self.evidence_layer

    @property
    def deployment_profile(self) -> LayerProvenance:
        return self.deployment_profile_layer

    @property
    def domain_overlay(self) -> LayerProvenance:
        return self.domain_overlay_layer

    @property
    def authorization(self) -> LayerProvenance:
        return self.authorization_layer

    @property
    def tool(self) -> LayerProvenance:
        return self.tool_layer

    @property
    def final(self) -> LayerProvenance:
        return self.final_composition


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


def _first_layer(
    layers: Iterable[Mapping[str, Any]],
    sources: frozenset[str],
) -> dict[str, Any]:
    for layer in layers:
        source = str(layer.get("source") or "")
        if source in sources:
            return dict(layer)
    return {}


def extract_layer_snapshots(
    evaluation_layers: Iterable[Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Map evaluation layers into distinct provenance input snapshots.

    Does not use final composed admissibility as the evidence snapshot.
    """
    layers = list(evaluation_layers or [])
    return {
        "evidence": _first_layer(layers, _EVIDENCE_SOURCES),
        "deployment_profile": _first_layer(layers, _PROFILE_SOURCES),
        "domain_overlay": _first_layer(layers, _OVERLAY_SOURCES),
        "tool": _first_layer(layers, _TOOL_SOURCES),
    }


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
    evaluation_layers: Iterable[Mapping[str, Any]] | None = None,
) -> DecisionLayerProvenance:
    """Assemble layered Decision provenance; evidence never satisfied by grant.

    When ``evaluation_layers`` is provided, per-layer decisions are taken from
    those snapshots. ``final_decision`` is recorded only on ``final_composition``
    and is never written into ``evidence_layer``.
    """
    assert_grant_cannot_satisfy_evidence()
    snapshots = extract_layer_snapshots(evaluation_layers)
    ev = snapshots["evidence"]
    prof = snapshots["deployment_profile"]
    overlay = snapshots["domain_overlay"]
    tool = snapshots["tool"]

    # Prefer explicit args; fall back to evaluation layer snapshots — never to final.
    evidence_decision = evidence_decision if evidence_decision is not None else ev.get("decision")
    evidence_reason = evidence_reason if evidence_reason is not None else ev.get("reason")
    deployment_profile_decision = (
        deployment_profile_decision
        if deployment_profile_decision is not None
        else prof.get("decision")
    )
    deployment_profile_reason = (
        deployment_profile_reason
        if deployment_profile_reason is not None
        else prof.get("reason")
    )
    domain_overlay_decision = (
        domain_overlay_decision
        if domain_overlay_decision is not None
        else overlay.get("decision")
    )
    domain_overlay_reason = (
        domain_overlay_reason
        if domain_overlay_reason is not None
        else overlay.get("reason")
    )
    tool_decision = tool_decision if tool_decision is not None else tool.get("decision")
    tool_reason = tool_reason if tool_reason is not None else tool.get("reason")

    auth_by_grant = bool(authorization_satisfied_by_grant and scope_grant is not None)
    return DecisionLayerProvenance(
        evidence_layer=LayerProvenance(
            layer="evidence_layer",
            decision=evidence_decision,
            reason=evidence_reason,
            satisfied_by_grant=False,
            source="evidence_rules",
        ),
        deployment_profile_layer=LayerProvenance(
            layer="deployment_profile_layer",
            decision=deployment_profile_decision,
            reason=deployment_profile_reason,
            satisfied_by_grant=False,
            source="deployment_profiles",
        ),
        domain_overlay_layer=LayerProvenance(
            layer="domain_overlay_layer",
            decision=domain_overlay_decision,
            reason=domain_overlay_reason,
            satisfied_by_grant=False,
            source="domain_overlay",
        ),
        authorization_layer=LayerProvenance(
            layer="authorization_layer",
            decision=authorization_decision,
            reason=authorization_reason,
            satisfied_by_grant=auth_by_grant,
            source="scope_grant" if auth_by_grant else "authorization",
        ),
        tool_layer=LayerProvenance(
            layer="tool_layer",
            decision=tool_decision,
            reason=tool_reason,
            satisfied_by_grant=False,
            source="tool_registry",
        ),
        final_composition=LayerProvenance(
            layer="final_composition",
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
            authorization_decision="authorization_satisfied" if scope_grant else None,
            tool_decision=(pre.get("unknown_consequential_tool") or {}).get("decision"),
            final_decision=post_decision,
            final_reason=post_reason,
            scope_grant=scope_grant,
            authorization_satisfied_by_grant=True,
        )
    if layers is not None and layers.evidence_layer.satisfied_by_grant:
        violations.append("evidence layer marked satisfied_by_grant")
    if layers is not None and not layers.evidence_never_satisfied_by_grant:
        violations.append("layered provenance missing evidence_never_satisfied_by_grant")
    if layers is not None:
        # Invariant: final composition must not equal evidence_layer when only
        # the final was supplied (detects accidental feed-back).
        if (
            layers.final_composition.decision is not None
            and layers.evidence_layer.decision == layers.final_composition.decision
            and layers.evidence_layer.reason == layers.final_composition.reason
            and layers.evidence_layer.source == "composed"
        ):
            violations.append(
                "evidence_layer must not be populated from final_composition"
            )

    return EvidenceIndependenceResult(
        ok=not violations, violations=violations, layers=layers
    )


def attach_layer_provenance_to_decision(
    decision: dict[str, Any],
    provenance: DecisionLayerProvenance,
) -> dict[str, Any]:
    """Record layered provenance on a Decision dict (non-destructive copy)."""
    out = dict(decision)
    prov_dict = provenance.to_dict()
    out["decision_layer_provenance"] = prov_dict
    # Preserve legacy grant_layer_satisfaction shape when present.
    satisfaction = dict(out.get("grant_layer_satisfaction") or {})
    satisfaction["evidence_never_satisfied_by_grant"] = True
    satisfaction["decision_layers"] = {
        name: prov_dict[name] for name in DECISION_PROVENANCE_LAYERS
    }
    out["grant_layer_satisfaction"] = satisfaction
    return out


def provenance_objects_for_authorization(
    provenance: DecisionLayerProvenance,
) -> dict[str, Any]:
    """Distinct layer objects for authorization_provenance (never composed blob)."""
    d = provenance.to_dict()
    return {
        "evidence_layer": d["evidence_layer"],
        "deployment_profile_layer": d["deployment_profile_layer"],
        "domain_overlay_layer": d["domain_overlay_layer"],
        "authorization_layer": d["authorization_layer"],
        "tool_layer": d["tool_layer"],
        "final_composition": d["final_composition"],
        "evidence_never_satisfied_by_grant": d["evidence_never_satisfied_by_grant"],
    }
