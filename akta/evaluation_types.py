"""Shared evaluation result types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvaluationLayer:
    """Single policy layer contribution."""

    source: str
    decision: str
    reason: str


@dataclass
class EvaluationResult:
    """Composed admissibility evaluation."""

    admissibility: str
    layers: list[EvaluationLayer] = field(default_factory=list)
    decision_reason: str = ""
    required_review_role: str | None = None
    blocked_tools: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    next_admissible_steps: list[str] = field(default_factory=list)
    review_required: bool = False
    authorization_required: bool = False
    record_required: bool = True
    consequentiality: bool = False
    consequentiality_reason: str = ""
