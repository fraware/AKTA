"""Consequentiality classification for admissibility decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from akta.classify import action_rank, responsibility_rank
from akta.context import AKTAContext
from akta.overlays import DomainOverlay
from akta.tool_registry import ToolSpec

CONSEQUENTIAL_ACTIONS = frozenset({
    "A4_recommendation",
    "A5_protocol_modification",
    "A6_experimental_planning",
    "A7_resource_or_queue_prioritization",
    "A8_tool_or_workflow_mutation",
    "A9_execution_adjacent_or_external_action",
    "A10_publication_or_claim_escalation",
})

PUBLICATION_KEYWORDS = (
    "publish", "manuscript", "paper", "grant", "claim", "breakthrough",
    "next run", "should run", "prioriti", "queue", "schedule",
)


@dataclass
class ConsequentialityResult:
    """Whether the requested action has downstream scientific consequences.

    Used to distinguish informational interpretation from language that implies
    next-run, prioritization, or publication pathways under ``allowed_log_or_review``.
    """

    consequential: bool
    reason: str


def classify_consequentiality(
    action_type: str,
    tool_spec: ToolSpec,
    requested_tool: str,
    requested_action: str,
    ai_output: Any,
    context: AKTAContext,
    overlay: DomainOverlay | None = None,
) -> ConsequentialityResult:
    """Determine if the action is consequential for alias resolution and logging."""
    reasons: list[str] = []

    if tool_spec.mutates_state:
        reasons.append("mutating tool")
    if context.consequential is True:
        reasons.append("context.consequential flag")
    if context.metadata:
        if context.metadata.get("consequential") is True:
            reasons.append("metadata.consequential flag")
        if context.metadata.get("mutates_external_state"):
            reasons.append("metadata mutates_external_state")
    structured = context.structured_action or context.tool_payload or {}
    if structured.get("consequential") is True:
        reasons.append("structured consequential signal")
    if structured.get("external_effect") is True:
        reasons.append("structured external_effect")
    if tool_spec.external_effect:
        reasons.append("external effect")
    if action_type in CONSEQUENTIAL_ACTIONS:
        reasons.append(f"action type {action_type}")
    if action_type == "A5_protocol_modification" and "active" in requested_tool.lower():
        reasons.append("active protocol mutation")
    if action_type == "A10_publication_or_claim_escalation":
        reasons.append("publication pathway")
    if action_type == "A7_resource_or_queue_prioritization":
        reasons.append("resource allocation")

    text = _output_text(ai_output, requested_action)
    lower = text.lower()
    if any(kw in lower for kw in PUBLICATION_KEYWORDS):
        if "next run" in lower or "should run" in lower or "prioriti" in lower:
            reasons.append("next-run or prioritization language")
        if any(kw in lower for kw in ("publish", "manuscript", "grant", "claim")):
            reasons.append("publication or claim language")

    if overlay is not None:
        if action_type in overlay.blocked_actions():
            reasons.append("overlay hazard")
        min_ev = overlay.minimum_evidence_for()
        if action_type == "A4_recommendation" and "recommendation" in min_ev:
            reasons.append("overlay recommendation threshold")

    handoff = context.handoff_chain or []
    if len(handoff) >= 2:
        ranks = [
            responsibility_rank(h.get("responsibility_level", ""))
            for h in handoff
            if h.get("responsibility_level")
        ]
        if ranks and max(ranks) - min(ranks) >= 2:
            reasons.append("handoff escalation")

    if action_type == "A3_evidence_interpretation" and not reasons:
        return ConsequentialityResult(False, "non-consequential evidence interpretation")

    if reasons:
        return ConsequentialityResult(True, "; ".join(dict.fromkeys(reasons)))

    if action_rank(action_type) >= action_rank("A3_evidence_interpretation"):
        return ConsequentialityResult(True, f"action type {action_type}")

    return ConsequentialityResult(False, "non-consequential informational action")


def _output_text(ai_output: Any, requested_action: str) -> str:
    if isinstance(ai_output, str):
        return ai_output
    if isinstance(ai_output, dict):
        return str(ai_output.get("summary") or ai_output.get("text") or requested_action)
    return requested_action
