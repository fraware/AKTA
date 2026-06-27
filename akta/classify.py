"""Deterministic scientific action classification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from akta.context import AKTAContext
from akta.policy import PolicyBundle
from akta.tool_registry import ToolSpec


ACTION_ORDER = {
    "A0_explanation": 0,
    "A1_retrieval_or_summary": 1,
    "A2_hypothesis_generation": 2,
    "A3_evidence_interpretation": 3,
    "A4_recommendation": 4,
    "A5_protocol_modification": 5,
    "A6_experimental_planning": 6,
    "A7_resource_or_queue_prioritization": 7,
    "A8_tool_or_workflow_mutation": 8,
    "A9_execution_adjacent_or_external_action": 9,
    "A10_publication_or_claim_escalation": 10,
}

RESPONSIBILITY_ORDER = {
    "R0_informational_assistance": 0,
    "R1_epistemic_assistance": 1,
    "R2_analytical_assistance": 2,
    "R3_consequential_interpretation": 3,
    "R4_methodological_modification": 4,
    "R5_experimental_planning": 5,
    "R6_resource_allocation": 6,
    "R7_execution_adjacent_preparation": 7,
    "R8_external_or_physical_execution": 8,
    "R9_publication_or_institutional_claim": 9,
}

ACTION_KEYWORDS: list[tuple[str, str]] = [
    (r"prioriti|queue|schedule|allocate|rank.*sample", "A7_resource_or_queue_prioritization"),
    (r"protocol.*(edit|update|change|modify)|update.*protocol|threshold|timing", "A5_protocol_modification"),
    (r"run.?plan|experiment.*plan|validation.*plan|create.*plan", "A6_experimental_planning"),
    (r"robot|submit.*queue|execution|physical|procurement", "A9_execution_adjacent_or_external_action"),
    (r"publish|claim|grant|manuscript|paper", "A10_publication_or_claim_escalation"),
    (r"recommend|suggest.*next|should.*run", "A4_recommendation"),
    (r"interpret|analyze|analysis", "A3_evidence_interpretation"),
    (r"hypothesis|mechanism|propose", "A2_hypothesis_generation"),
    (r"summarize|retrieve|literature|search", "A1_retrieval_or_summary"),
    (r"explain|describe|what is", "A0_explanation"),
]


@dataclass
class ClassificationResult:
    """Classification output."""

    action_type: str
    responsibility_level: str
    confidence: float
    rationale: str


def action_rank(action_type: str) -> int:
    return ACTION_ORDER.get(action_type, 8)


def responsibility_rank(level: str) -> int:
    return RESPONSIBILITY_ORDER.get(level, 0)


def action_to_responsibility(policy: PolicyBundle, action_type: str) -> str:
    mapping = policy.responsibility_levels.get("action_to_responsibility", {})
    return mapping.get(action_type, "R3_consequential_interpretation")


def classify_from_action_text(requested_action: str) -> str | None:
    text = requested_action.lower()
    for pattern, action_type in ACTION_KEYWORDS:
        if re.search(pattern, text):
            return action_type
    return None


def infer_evidence_from_vsa(vsa_report: dict[str, Any] | None) -> str | None:
    if not vsa_report:
        return None
    if "evidence_state" in vsa_report:
        return vsa_report["evidence_state"]
    strength = vsa_report.get("overall_evidence_strength") or vsa_report.get("evidence_strength")
    mapping = {
        "none": "E0_no_evidence",
        "no_evidence": "E0_no_evidence",
        "anecdotal": "E1_anecdotal_or_informal_observation",
        "preliminary": "E2_preliminary_signal",
        "weak": "E2_preliminary_signal",
        "noisy": "E3_noisy_or_conflicting_evidence",
        "conflicting": "E3_noisy_or_conflicting_evidence",
        "consistent": "E4_internally_consistent_evidence",
        "replicated": "E5_internally_replicated_evidence",
        "independent": "E6_independently_reproduced_evidence",
        "validated": "E7_deployment_validated_evidence",
    }
    if strength and isinstance(strength, str):
        return mapping.get(strength.lower(), None)
    claims = vsa_report.get("claims", [])
    if claims:
        levels = [c.get("evidence_level", "") for c in claims if isinstance(c, dict)]
        if any("preliminary" in str(l).lower() or "weak" in str(l).lower() for l in levels):
            return "E2_preliminary_signal"
    return None


def infer_validation_from_vsa(vsa_report: dict[str, Any] | None) -> str | None:
    if not vsa_report:
        return None
    if "validation_status" in vsa_report:
        return vsa_report["validation_status"]
    results = vsa_report.get("validation_results", {})
    if results.get("independently_replicated"):
        return "V5_independently_replicated"
    if results.get("internally_replicated"):
        return "V4_internally_replicated"
    if results.get("preliminary_experimental"):
        return "V3_preliminary_experimental_support"
    if results.get("simulation_supported"):
        return "V2_simulation_supported"
    if results.get("literature_supported"):
        return "V1_literature_supported"
    return None


def classify(
    policy: PolicyBundle,
    requested_tool: str,
    requested_action: str,
    tool_spec: ToolSpec,
    context: AKTAContext,
    ai_output: Any = None,
) -> ClassificationResult:
    """Classify scientific action type and responsibility level."""
    action_type: str | None = None
    confidence = 0.95
    rationale_parts: list[str] = []

    if tool_spec.known:
        action_type = tool_spec.action_type
        rationale_parts.append(f"tool registry maps {requested_tool} to {action_type}")
        confidence = 0.98
    else:
        action_type = classify_from_action_text(requested_action)
        if action_type:
            rationale_parts.append(f"requested_action '{requested_action}' matched {action_type}")
            confidence = 0.85
        elif ai_output:
            text = ai_output if isinstance(ai_output, str) else str(
                ai_output.get("summary", ai_output) if isinstance(ai_output, dict) else ai_output
            )
            action_type = classify_from_action_text(text) or classify_from_action_text(requested_action)
            if action_type:
                rationale_parts.append("inferred from ai_output text")
                confidence = 0.75

    if not action_type:
        action_type = "A8_tool_or_workflow_mutation"
        rationale_parts.append("default to A8 for unclassified mutating request")
        confidence = 0.5

    responsibility_level = action_to_responsibility(policy, action_type)

    handoff_chain = context.handoff_chain or []
    if handoff_chain:
        max_handoff_action = action_type
        max_handoff_resp = responsibility_level
        for hop in handoff_chain:
            hop_action = hop.get("action_type", "")
            hop_resp = hop.get("responsibility_level", "")
            if action_rank(hop_action) > action_rank(max_handoff_action):
                max_handoff_action = hop_action
            if responsibility_rank(hop_resp) > responsibility_rank(max_handoff_resp):
                max_handoff_resp = hop_resp
        if action_rank(max_handoff_action) > action_rank(action_type):
            action_type = max_handoff_action
            responsibility_level = action_to_responsibility(policy, action_type)
            rationale_parts.append("escalated via handoff chain action type")
        if responsibility_rank(max_handoff_resp) > responsibility_rank(responsibility_level):
            responsibility_level = max_handoff_resp
            rationale_parts.append("escalated via handoff chain responsibility")

    return ClassificationResult(
        action_type=action_type,
        responsibility_level=responsibility_level,
        confidence=confidence,
        rationale="; ".join(rationale_parts) or "deterministic classification",
    )


def resolve_evidence_state(context: AKTAContext) -> str:
    if context.evidence_state:
        return context.evidence_state
    vsa_state = infer_evidence_from_vsa(context.vsa_report)
    if vsa_state:
        return vsa_state
    return "E0_no_evidence"


def resolve_validation_status(context: AKTAContext) -> str:
    if context.validation_status:
        return context.validation_status
    vsa_val = infer_validation_from_vsa(context.vsa_report)
    if vsa_val:
        return vsa_val
    return "V0_unvalidated"


def resolve_verification_status(context: AKTAContext) -> str:
    return context.verification_status or "Q0_unchecked"
