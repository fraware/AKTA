"""Deterministic scientific action classification."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from akta.classifier_plugins import run_plugin_classification
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

CONFIDENCE_THRESHOLD = 0.7


@dataclass
class ClassificationResult:
    """Rich classification output (v0.2).

    Attributes:
        action_type: Resolved AKTA action ontology identifier (e.g. ``A7_resource_or_queue_prioritization``).
        responsibility_level: Mapped responsibility tier (e.g. ``R6_resource_allocation``).
        confidence: Classifier confidence in ``[0, 1]``; low values trigger fail-closed admissibility.
        rationale: Human-readable audit string explaining the classification path.
        alternate_action_types: Other action types considered from NL or plugin input.
        matched_source: Provenance of the primary classification (tool_registry, requested_action, plugin, etc.).
        matched_evidence: Short pointer to the signal used (tool name, action text, etc.).
        uncertainty_flags: Taxonomy flags such as ``nl_tool_mismatch`` or ``model_assisted_fallback``.
        classifier_mode: ``deterministic`` or ``llm_advisory`` when a plugin contributed.
        llm_metadata: Model, prompt_hash, schema, confidence when LLM advisory path used.
    """

    action_type: str
    responsibility_level: str
    confidence: float
    rationale: str
    alternate_action_types: list[str] = field(default_factory=list)
    matched_source: str = "deterministic"
    matched_evidence: str = ""
    uncertainty_flags: list[str] = field(default_factory=list)
    classifier_mode: str = "deterministic"
    llm_metadata: dict[str, Any] | None = None

    @property
    def primary_action_type(self) -> str:
        """Primary action type alias for record export."""
        return self.action_type


def action_rank(action_type: str) -> int:
    return ACTION_ORDER.get(action_type, 8)


def responsibility_rank(level: str) -> int:
    return RESPONSIBILITY_ORDER.get(level, 0)


def action_to_responsibility(policy: PolicyBundle, action_type: str) -> str:
    mapping = policy.responsibility_levels.get("action_to_responsibility", {})
    return mapping.get(action_type, "R3_consequential_interpretation")


def classify_from_structured_action(
    structured: dict[str, Any] | None,
    tool_payload: dict[str, Any] | None,
) -> tuple[str | None, str, list[str]]:
    """Resolve action type from structured context (priority over regex)."""
    if structured and structured.get("action_type"):
        action = str(structured["action_type"])
        source = "structured_action"
        alts = list(structured.get("alternate_action_types") or [])
        return action, source, alts
    if tool_payload and tool_payload.get("action_type"):
        action = str(tool_payload["action_type"])
        source = "tool_payload"
        alts = list(tool_payload.get("alternate_action_types") or [])
        return action, source, alts
    return None, "", []


def detect_handoff_authority_transfer(chain: list[dict[str, Any]]) -> bool:
    """True when responsibility monotonically escalates across the handoff chain."""
    ranks = [
        responsibility_rank(h.get("responsibility_level", ""))
        for h in chain
        if h.get("responsibility_level")
    ]
    if len(ranks) < 2:
        return False
    return all(ranks[i] <= ranks[i + 1] for i in range(len(ranks) - 1)) and ranks[-1] > ranks[0]


_NEGATION_PREFIX = re.compile(r"\b(do not|don't|never|without|not to|avoid)\b")
_HEDGING_PREFIX = re.compile(r"\b(might|may|could|possibly|perhaps|tentatively)\b")
_AUTHORITY_TRANSFER = re.compile(
    r"\b(on your behalf|execute for me|go ahead and|take care of|handle this for me|"
    r"proceed with (the )?(submission|execution|order|purchase|deployment))\b"
)


def detect_prose_authority_transfer(text: str) -> bool:
    """Detect authority-transfer phrasing in NL prose."""
    return bool(_AUTHORITY_TRANSFER.search(text.lower()))


def detect_hedging(text: str) -> bool:
    """Detect hedging language that lowers classification confidence."""
    return bool(_HEDGING_PREFIX.search(text.lower()))


def _keyword_match_negated(text: str, match_start: int) -> bool:
    """True when a negation cue appears shortly before the keyword match."""
    window = text[max(0, match_start - 48) : match_start]
    return bool(_NEGATION_PREFIX.search(window))


def classify_from_action_text(requested_action: str) -> tuple[str | None, list[str]]:
    text = requested_action.lower().replace("_", " ")
    matches: list[str] = []
    for pattern, action_type in ACTION_KEYWORDS:
        hit = re.search(pattern, text)
        if hit and not _keyword_match_negated(text, hit.start()):
            matches.append(action_type)
    if not matches:
        return None, []
    return matches[0], matches[1:]


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
    alternates: list[str] = []
    confidence = 0.95
    rationale_parts: list[str] = []
    matched_source = "deterministic"
    matched_evidence = ""
    uncertainty_flags: list[str] = []
    classifier_mode = "deterministic"

    structured_action, structured_source, structured_alts = classify_from_structured_action(
        context.structured_action, context.tool_payload
    )
    if structured_action:
        action_type = structured_action
        matched_source = structured_source
        matched_evidence = structured_source
        alternates.extend(structured_alts)
        rationale_parts.append(f"{structured_source} specifies {structured_action}")
        confidence = 0.99

    plugin_result = None
    if not structured_action:
        plugin_result = run_plugin_classification(
            policy,
            requested_tool,
            requested_action,
            tool_spec,
            context,
            ai_output=ai_output,
        )

    if tool_spec.known and not structured_action:
        action_type = tool_spec.action_type
        matched_source = "tool_registry"
        matched_evidence = f"tool={requested_tool}"
        rationale_parts.append(f"tool registry maps {requested_tool} to {action_type}")
        confidence = 0.98
        nl_action, nl_alts = classify_from_action_text(requested_action)
        if nl_action and nl_action != action_type:
            alternates.append(nl_action)
            alternates.extend(nl_alts)
            uncertainty_flags.append("nl_tool_mismatch")
            rationale_parts.append(
                f"NL text suggests {nl_action} but tool registry overrides to {action_type}"
            )
        if plugin_result is not None and plugin_result.action_type != action_type:
            alternates.append(plugin_result.action_type)
            uncertainty_flags.append("llm_overridden_by_tool_registry")
            rationale_parts.append(
                f"LLM suggested {plugin_result.action_type} but tool registry overrides"
            )
    else:
        if not action_type:
            nl_action, nl_alts = classify_from_action_text(requested_action)
            alternates.extend(nl_alts)
            if nl_action:
                action_type = nl_action
                matched_source = "requested_action"
                matched_evidence = f"action={requested_action}"
                rationale_parts.append(f"requested_action '{requested_action}' matched {action_type}")
                confidence = 0.85
            elif ai_output:
                text = ai_output if isinstance(ai_output, str) else str(
                    ai_output.get("summary", ai_output) if isinstance(ai_output, dict) else ai_output
                )
                if detect_prose_authority_transfer(text):
                    uncertainty_flags.append("prose_authority_transfer")
                    confidence = min(confidence, 0.65)
                if detect_hedging(text):
                    uncertainty_flags.append("hedging_language")
                    confidence = min(confidence, 0.72)
                ai_action, ai_alts = classify_from_action_text(text) or (None, [])
                if not ai_action:
                    ai_action, ai_alts = classify_from_action_text(requested_action)
                alternates.extend(ai_alts)
                if ai_action:
                    action_type = ai_action
                    matched_source = "ai_output"
                    matched_evidence = "ai_output text"
                    rationale_parts.append("inferred from ai_output text")
                    confidence = 0.75

    if not action_type and plugin_result is not None:
        classifier_mode = "llm_advisory" if plugin_result.source == "llm_classifier" else "plugin_assisted"
        action_type = plugin_result.action_type
        confidence = plugin_result.confidence
        alternates.extend(plugin_result.alternates)
        uncertainty_flags.extend(plugin_result.uncertainty_flags)
        matched_source = plugin_result.source
        matched_evidence = f"plugin={plugin_result.source}"
        rationale_parts.append(plugin_result.rationale)
        llm_metadata = plugin_result.llm_metadata
    else:
        llm_metadata = None

    if not action_type:
        action_type = "A8_tool_or_workflow_mutation"
        matched_source = "default_fail_closed"
        rationale_parts.append("default to A8 for unclassified mutating request")
        confidence = 0.5
        uncertainty_flags.append("unclassified_mutating_request")

    if len(alternates) > 1 or (alternates and confidence < CONFIDENCE_THRESHOLD):
        uncertainty_flags.append("ambiguous_wording")

    nl_text = requested_action.lower().replace("_", " ")
    if ai_output and isinstance(ai_output, str):
        nl_text = f"{nl_text} {ai_output.lower()}"
    elif isinstance(ai_output, dict) and ai_output.get("summary"):
        nl_text = f"{nl_text} {str(ai_output['summary']).lower()}"
    if detect_prose_authority_transfer(nl_text) and not structured_action:
        uncertainty_flags.append("prose_authority_transfer")
        confidence = min(confidence, 0.65)

    responsibility_level = action_to_responsibility(policy, action_type)

    handoff_chain = context.handoff_chain or []
    if handoff_chain:
        if detect_handoff_authority_transfer(handoff_chain):
            uncertainty_flags.append("handoff_authority_transfer")
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
            matched_source = "handoff_chain"
            matched_evidence = "handoff escalation"
            rationale_parts.append("escalated via handoff chain action type")
            uncertainty_flags.append("handoff_escalation")
        if responsibility_rank(max_handoff_resp) > responsibility_rank(responsibility_level):
            responsibility_level = max_handoff_resp
            rationale_parts.append("escalated via handoff chain responsibility")

    return ClassificationResult(
        action_type=action_type,
        responsibility_level=responsibility_level,
        confidence=confidence,
        rationale="; ".join(rationale_parts) or "deterministic classification",
        alternate_action_types=list(dict.fromkeys(alternates)),
        matched_source=matched_source,
        matched_evidence=matched_evidence,
        uncertainty_flags=list(dict.fromkeys(uncertainty_flags)),
        classifier_mode=classifier_mode,
        llm_metadata=llm_metadata if classifier_mode == "llm_advisory" else None,
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
