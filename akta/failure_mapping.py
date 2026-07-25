"""Map repo-specific failures into ten uniform classes (AS-04)."""

from __future__ import annotations

import re
from typing import Any

from akta.errors import (
    AKTAError,
    AKTAReviewRequired,
    GrantVerificationError,
    InsufficientAuthorizationContext,
    PolicyError,
    SchemaValidationError,
    ToolRegistryError,
    UnsupportedProfileError,
)
from akta.records import validate_against_schema

UNIFORM_CLASSES = (
    "invalid_input",
    "insufficient_evidence",
    "policy_block",
    "review_required",
    "authorization_denied",
    "runtime_constraint_violation",
    "verification_failed",
    "verification_indeterminate",
    "external_dependency_failure",
    "outcome_unresolved",
)

# Bench F-class aliases: normalize F1_ → F01_ in mapper only.
_F_CLASS_RE = re.compile(r"^F(\d)_(.+)$")
_F_CLASS_FULL = re.compile(r"^F(\d{2})_(.+)$")


def normalize_failure_class_code(code: str) -> str:
    """Normalize F1_foo → F01_foo; leave F01_foo unchanged."""
    text = str(code or "").strip()
    m = _F_CLASS_FULL.match(text)
    if m:
        return f"F{m.group(1)}_{m.group(2)}"
    m = _F_CLASS_RE.match(text)
    if m:
        return f"F0{m.group(1)}_{m.group(2)}"
    return text


_LOCAL_TO_UNIFORM: dict[str, tuple[str, str, bool]] = {
    # local_reason → (uniform_class, layer, recoverable)
    "schema_validation": ("invalid_input", "schema", True),
    "invalid_input": ("invalid_input", "input", True),
    "unsupported_profile": ("policy_block", "deployment_profile", False),
    "policy_error": ("policy_block", "policy", False),
    "policy_block": ("policy_block", "policy", False),
    "pilot_mode_restriction": ("policy_block", "pilot_mode", True),
    "pilot_exclusion": ("policy_block", "pilot_mode", False),
    "insufficient_evidence": ("insufficient_evidence", "evidence_rules", True),
    "weak_evidence": ("insufficient_evidence", "evidence_rules", True),
    "F01_weak_evidence_escalation": ("insufficient_evidence", "evidence_rules", True),
    "review_required": ("review_required", "review", True),
    "authorization_required": ("authorization_denied", "authorization", True),
    "authorization_denied": ("authorization_denied", "authorization", False),
    "grant_verification": ("verification_failed", "scope_grant", True),
    "verification_failed": ("verification_failed", "verification", False),
    "verification_indeterminate": ("verification_indeterminate", "verification", True),
    "tool_registry": ("runtime_constraint_violation", "tool_registry", True),
    "runtime_constraint": ("runtime_constraint_violation", "runtime", False),
    "external_dependency": ("external_dependency_failure", "external", True),
    "outcome_unresolved": ("outcome_unresolved", "outcome", True),
    "outcome_mutation_rejected": ("policy_block", "outcome", False),
}


def map_local_reason(
    local_reason_code: str,
    *,
    detail: str = "",
    layer: str | None = None,
    recoverable: bool | None = None,
    next_admissible_steps: list[str] | None = None,
    validate: bool = True,
) -> dict[str, Any]:
    code = normalize_failure_class_code(local_reason_code)
    mapped = _LOCAL_TO_UNIFORM.get(code)
    if mapped is None:
        # Heuristic fallbacks from substrings — still preserve local code.
        lower = code.lower()
        if "evidence" in lower or "insufficient" in lower:
            mapped = ("insufficient_evidence", "evidence_rules", True)
        elif "review" in lower:
            mapped = ("review_required", "review", True)
        elif "authoriz" in lower or "grant" in lower:
            mapped = ("authorization_denied", "authorization", False)
        elif "verif" in lower:
            mapped = ("verification_failed", "verification", False)
        elif "external" in lower or "sibling" in lower:
            mapped = ("external_dependency_failure", "external", True)
        elif "outcome" in lower:
            mapped = ("outcome_unresolved", "outcome", True)
        elif "schema" in lower or "invalid" in lower:
            mapped = ("invalid_input", "input", True)
        else:
            mapped = ("policy_block", "policy", False)

    uniform, default_layer, default_recoverable = mapped
    failure = {
        "uniform_class": uniform,
        "local_reason_code": code,
        "detail": detail or code,
        "layer": layer or default_layer,
        "recoverable": default_recoverable if recoverable is None else recoverable,
    }
    if next_admissible_steps is not None:
        failure["next_admissible_steps"] = list(next_admissible_steps)
    if validate:
        validate_against_schema(failure, "uniform_failure.schema.json")
    return failure


def map_exception(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, SchemaValidationError):
        return map_local_reason("schema_validation", detail=str(exc), layer="schema")
    if isinstance(exc, UnsupportedProfileError):
        return map_local_reason("unsupported_profile", detail=str(exc), layer="deployment_profile")
    if isinstance(exc, PolicyError):
        return map_local_reason("policy_error", detail=str(exc), layer="policy")
    if isinstance(exc, AKTAReviewRequired):
        return map_local_reason(
            "review_required",
            detail=str(exc),
            layer="review",
            recoverable=True,
        )
    if isinstance(exc, GrantVerificationError):
        return map_local_reason("grant_verification", detail=str(exc), layer="scope_grant")
    if isinstance(exc, InsufficientAuthorizationContext):
        return map_local_reason(
            "authorization_denied",
            detail=str(exc),
            layer="authorization",
            recoverable=True,
        )
    if isinstance(exc, ToolRegistryError):
        return map_local_reason("tool_registry", detail=str(exc), layer="tool_registry")
    if isinstance(exc, AKTAError):
        msg = str(exc)
        if "stale_" in msg or "digest_mismatch" in msg:
            return map_local_reason("verification_failed", detail=msg, layer="bindings")
        if "pilot_mode" in msg:
            return map_local_reason("pilot_mode_restriction", detail=msg, layer="pilot_mode")
        return map_local_reason("policy_block", detail=msg, layer="akta")
    return map_local_reason("runtime_constraint", detail=str(exc), layer="runtime")


def map_rest_error(error_code: str, *, detail: str = "") -> dict[str, Any]:
    """Map REST ``error_code`` while preserving the original code as local_reason."""
    code = str(error_code or "invalid_input")
    failure = map_local_reason(code, detail=detail or code, layer="rest_api")
    failure["error_code"] = code  # preserve prior API field
    return failure


def failures_for_decision(decision: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive uniform failures from a decision document when blocked/review."""
    adm = decision.get("admissibility")
    reason = str(decision.get("decision_reason") or "")
    steps = decision.get("next_admissible_steps")
    failures: list[dict[str, Any]] = []

    if adm in ("blocked", "abstain_insufficient_context"):
        local = "insufficient_evidence" if "evidence" in reason.lower() else "policy_block"
        # Prefer layer reason codes when present.
        for layer in decision.get("evaluation_layers") or []:
            layer_reason = str(layer.get("reason") or "")
            if layer.get("decision") in ("blocked", "abstain_insufficient_context"):
                if "evidence" in layer_reason.lower():
                    local = "insufficient_evidence"
                break
        failures.append(
            map_local_reason(
                local,
                detail=reason,
                layer="evaluate",
                next_admissible_steps=steps,
            )
        )
    elif adm == "review_required":
        failures.append(
            map_local_reason(
                "review_required",
                detail=reason,
                layer="evaluate",
                next_admissible_steps=steps,
            )
        )
    elif adm == "authorization_required":
        failures.append(
            map_local_reason(
                "authorization_denied",
                detail=reason,
                layer="evaluate",
                recoverable=True,
                next_admissible_steps=steps,
            )
        )
    return failures


__all__ = [
    "UNIFORM_CLASSES",
    "failures_for_decision",
    "map_exception",
    "map_local_reason",
    "map_rest_error",
    "normalize_failure_class_code",
]
