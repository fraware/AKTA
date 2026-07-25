"""Structured decision-basis builder (AS-03)."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from akta.records import validate_against_schema

DECISION_BASIS_VERSION = "akta-decision-basis-v1"

_CONFLICT_MARKERS = (
    "conflict",
    "contradict",
    "noisy",
    "E3_noisy",
    "inconsistent",
)

_WEAK_EVIDENCE = {
    "E0_no_evidence",
    "E1_anecdotal_or_informal_observation",
    "E2_preliminary_signal",
    "E3_noisy_or_conflicting_evidence",
}


def _tool_effect_class(tool_spec: Any) -> str:
    if tool_spec is None:
        return "unknown"
    if is_dataclass(tool_spec):
        spec = asdict(tool_spec)
    elif isinstance(tool_spec, dict):
        spec = tool_spec
    else:
        spec = {
            "mutates_state": getattr(tool_spec, "mutates_state", False),
            "external_effect": getattr(tool_spec, "external_effect", False),
            "known": getattr(tool_spec, "known", True),
        }
    if not spec.get("known", True):
        return "unknown_tool"
    if spec.get("mutates_state") and spec.get("external_effect"):
        return "mutating_external"
    if spec.get("mutates_state"):
        return "mutating_internal"
    if spec.get("external_effect"):
        return "external_readonly"
    return "analysis_query"


def _action_risk_class(action_class: str, admissibility: str) -> str:
    if admissibility in ("blocked", "abstain_insufficient_context"):
        return "high_refusal"
    if admissibility in ("review_required", "authorization_required"):
        return "elevated_review"
    if action_class.startswith("A8") or "mutation" in (action_class or "").lower():
        return "consequential_mutation"
    if action_class.startswith("A1") or "literature" in (action_class or "").lower():
        return "low_analysis"
    return "standard"


def build_decision_basis(
    *,
    evaluation_layers: list[dict[str, Any]],
    evidence_state: str,
    admissibility: str,
    decision_reason: str,
    next_admissible_steps: list[str] | None,
    required_review_role: str | None,
    action_class: str,
    tool_spec: Any = None,
    policy: Any = None,
    overlay: Any = None,
    context: dict[str, Any] | None = None,
    validate: bool = True,
) -> dict[str, Any]:
    """Build decision basis from real evaluation layers and loaded policy keys."""
    ctx = context or {}
    clauses: list[dict[str, Any]] = []
    for layer in evaluation_layers or []:
        source = str(layer.get("source") or "unknown")
        clauses.append(
            {
                "clause_id": f"{source}:{layer.get('decision')}",
                "source": source,
                "summary": str(layer.get("reason") or ""),
            }
        )

    # Cite real policy structure keys when available — never invent clause IDs.
    if policy is not None:
        version = getattr(policy, "version", None) or (policy.get("version") if isinstance(policy, dict) else None)
        if version:
            clauses.append(
                {
                    "clause_id": f"policy_bundle:{version}",
                    "source": "policy_bundle",
                    "summary": f"Loaded policy bundle version {version}",
                }
            )
        profiles = getattr(policy, "deployment_profiles", None)
        if profiles is None and isinstance(policy, dict):
            profiles = policy.get("deployment_profiles")
        if isinstance(profiles, dict) and profiles:
            clauses.append(
                {
                    "clause_id": "deployment_profiles",
                    "source": "policy_bundle",
                    "summary": f"Profiles loaded: {', '.join(sorted(profiles.keys())[:12])}",
                }
            )
        evidence_rules = getattr(policy, "evidence_rules", None)
        if evidence_rules is None and isinstance(policy, dict):
            evidence_rules = policy.get("evidence_rules")
        if evidence_rules is not None:
            clauses.append(
                {
                    "clause_id": "evidence_rules",
                    "source": "policy_bundle",
                    "summary": "Evidence-to-action rules applied",
                }
            )

    if overlay is not None:
        ov_name = getattr(overlay, "name", None) or getattr(overlay, "domain", None)
        ov_hash = getattr(overlay, "overlay_hash", None)
        clauses.append(
            {
                "clause_id": f"domain_overlay:{ov_name or 'loaded'}",
                "source": "domain_overlay",
                "summary": f"Overlay hash {ov_hash}" if ov_hash else "Domain overlay applied",
            }
        )

    evidence_present: list[str] = []
    missing_evidence: list[str] = []
    contradictions: list[str] = []
    evidence_requirements = [
        "evidence_state",
        "validation_status",
        "verification_status",
    ]

    if evidence_state:
        evidence_present.append(f"evidence_state:{evidence_state}")
    if ctx.get("vsa_bundle") or ctx.get("vsa_report"):
        evidence_present.append("vsa_decision_time_bundle")
    if ctx.get("validation_status"):
        evidence_present.append(f"validation_status:{ctx.get('validation_status')}")

    if evidence_state in _WEAK_EVIDENCE or evidence_state is None:
        missing_evidence.append("sufficient_replicated_evidence")
    if not (ctx.get("vsa_bundle") or ctx.get("vsa_report")):
        missing_evidence.append("vsa_decision_time_bundle")

    blob = " ".join(
        [
            evidence_state or "",
            decision_reason or "",
            *[str(c.get("summary") or "") for c in clauses],
        ]
    ).lower()
    if any(m.lower() in blob for m in _CONFLICT_MARKERS) or evidence_state == "E3_noisy_or_conflicting_evidence":
        contradictions.append("conflicting_or_noisy_evidence_signal")
        meta = ctx.get("metadata") or {}
        if meta.get("contradictions"):
            for item in meta["contradictions"]:
                contradictions.append(str(item))

    roles: list[str] = []
    if required_review_role:
        roles.append(required_review_role)

    steps = list(next_admissible_steps or [])
    # Constructive surface must not silently empty on blocks.
    if not steps:
        if admissibility in ("blocked", "abstain_insufficient_context", "review_required"):
            steps = [
                "strengthen_evidence_or_validation",
                "request_human_review_if_policy_allows",
                "narrow_requested_tool_to_analysis_query",
            ]
        else:
            steps = ["proceed_within_allowed_tools"]

    pf_obligations: list[str] = []
    if admissibility in ("blocked", "abstain_insufficient_context"):
        pf_obligations.append("tool_block")
    elif admissibility == "authorization_required":
        pf_obligations.append("tool_authorize")
    elif admissibility in ("review_required", "draft_only"):
        pf_obligations.append("tool_review")
    else:
        pf_obligations.append("tool_allow")

    basis = {
        "decision_basis_version": DECISION_BASIS_VERSION,
        "applicable_policy_clauses": clauses,
        "evidence_requirements": evidence_requirements,
        "evidence_present": sorted(set(evidence_present)),
        "missing_evidence": sorted(set(missing_evidence)),
        "contradictions": sorted(set(contradictions)),
        "action_risk_class": _action_risk_class(action_class, admissibility),
        "tool_effect_class": _tool_effect_class(tool_spec),
        "required_reviewer_roles": roles,
        "generated_pf_obligations": pf_obligations,
        "next_admissible_steps": steps,
    }
    if validate:
        validate_against_schema(basis, "decision_basis.schema.json")
    return basis


__all__ = ["DECISION_BASIS_VERSION", "build_decision_basis"]
