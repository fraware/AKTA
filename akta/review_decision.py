"""Review decision import schema stub and loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from akta.records import validate_against_schema


def load_review_decision(path: str | Path, *, validate: bool = True) -> dict[str, Any]:
    """Load and optionally validate a SCOPE review decision artifact."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if validate:
        validate_against_schema(data, "review_decision.schema.json")
    return data


def apply_review_decision_to_context(
    context: dict[str, Any],
    review_decision: dict[str, Any],
) -> dict[str, Any]:
    """Map an imported review decision into AKTA context metadata."""
    metadata = dict(context.get("metadata") or {})
    metadata["prior_review_id"] = review_decision.get("review_decision_id")
    metadata["prior_review_scope"] = review_decision.get("granted_scope")
    metadata["prior_review_decision"] = review_decision.get("decision")
    metadata["prior_review_expired"] = False
    if review_decision.get("expires_at"):
        metadata["prior_review_expires_at"] = review_decision["expires_at"]
    context = dict(context)
    context["metadata"] = metadata
    return context
