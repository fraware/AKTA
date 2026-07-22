"""SCOPE grant layer satisfaction (v1.0 RC hardening).

Doctrine (directive §2.1):
- A SCOPE grant may satisfy human_review / authorization requirements.
- A SCOPE grant must NEVER satisfy an empirical evidence requirement, convert
  weak evidence into strong evidence, or erase an evidence-based block.
- The boolean ``scope_grant_satisfies_evidence`` override is removed from the
  v1.0 release-candidate path. Legacy metadata keys are stripped and ignored.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from akta.scope_contract import _scope_grant_approved_scope

_AKTA_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_RULES_PATH = _AKTA_ROOT / "policy" / "scope_grant_override_rules.yaml"

# Layers a grant is permitted to satisfy. Evidence is intentionally absent.
GRANT_SATISFIABLE_LAYERS = frozenset({"human_review", "authorization"})
LEGACY_EVIDENCE_OVERRIDE_KEY = "scope_grant_satisfies_evidence"


def _grant_id(scope_grant: dict[str, Any]) -> str:
    return str(
        scope_grant.get("grant_id")
        or scope_grant.get("scope_grant_id")
        or (scope_grant.get("authorization") or {}).get("grant_id")
        or "SCOPE-GRANT-unspecified"
    )


@lru_cache(maxsize=4)
def load_grant_override_rules(rules_path: str | Path | None = None) -> dict[str, Any]:
    """Load grant review-satisfaction rules (evidence override disabled)."""
    path = Path(rules_path) if rules_path else _DEFAULT_RULES_PATH
    if not path.is_file():
        return {
            "default": "evidence_never_satisfied_by_grant",
            "grant_may_satisfy_evidence_layer": False,
            "rules": [],
        }
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data["grant_may_satisfy_evidence_layer"] = False
    return data


def grant_may_satisfy_evidence(
    *,
    deployment_profile: str = "",
    evidence_state: str = "",
    rules_path: str | Path | None = None,
) -> bool:
    """Always False: grants cannot satisfy the evidence layer (v1.0 RC).

    Retained for call-site compatibility. ``deployment_profile``,
    ``evidence_state``, and ``rules_path`` are ignored.
    """
    _ = (deployment_profile, evidence_state, rules_path, load_grant_override_rules(rules_path))
    return False


def compute_grant_layer_satisfaction(
    scope_grant: dict[str, Any],
    *,
    evidence_decision: str | None = None,
    evidence_reason: str | None = None,
) -> dict[str, Any]:
    """Build explicit layered satisfaction from a SCOPE grant.

    Satisfiable by grant: ``human_review``, ``authorization``.
    Never satisfiable by grant: ``evidence``.
    """
    grant_ref = _grant_id(scope_grant)
    scope = _scope_grant_approved_scope(scope_grant) or ""

    satisfied_layers: list[dict[str, Any]] = [
        {
            "layer": "human_review",
            "satisfied_by": grant_ref,
            "scope": scope,
            "transition": "review_required -> review_satisfied",
        },
        {
            "layer": "authorization",
            "satisfied_by": grant_ref,
            "scope": scope,
            "transition": "authorization_required -> authorization_satisfied",
        },
    ]

    unsatisfied_layers: list[dict[str, Any]] = []
    if evidence_decision and evidence_decision not in (
        "allowed",
        "allowed_with_logging",
        "draft_only",
    ):
        unsatisfied_layers.append(
            {
                "layer": "evidence",
                "decision": evidence_decision,
                "reason": evidence_reason
                or "Evidence layer remains independent of SCOPE grant authorization.",
            }
        )

    return {
        "satisfied_layers": satisfied_layers,
        "unsatisfied_layers": unsatisfied_layers,
        "evidence_never_satisfied_by_grant": True,
        "forbidden_transitions": [
            "blocked_by_evidence -> allowed (via SCOPE grant alone)",
        ],
    }


def strip_legacy_evidence_override(metadata: dict[str, Any]) -> dict[str, Any]:
    """Remove legacy boolean override keys from context metadata."""
    cleaned = dict(metadata)
    cleaned.pop(LEGACY_EVIDENCE_OVERRIDE_KEY, None)
    return cleaned


def apply_grant_override_metadata(
    context: dict[str, Any],
    *,
    deployment_profile: str = "",
    evidence_state: str = "",
    rules_path: str | Path | None = None,
    scope_grant: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach layered grant satisfaction; never skip the evidence layer.

    ``deployment_profile`` / ``evidence_state`` / ``rules_path`` are accepted for
    call-site compatibility but do not enable evidence override.
    """
    _ = (deployment_profile, evidence_state, rules_path)
    ctx = dict(context)
    metadata = strip_legacy_evidence_override(dict(ctx.get("metadata") or {}))

    if scope_grant is not None:
        metadata["grant_layer_satisfaction"] = compute_grant_layer_satisfaction(scope_grant)
    else:
        # Defensive: if a caller still injected the legacy flag, strip it.
        metadata.pop("grant_layer_satisfaction", None)

    ctx["metadata"] = metadata
    return ctx


def enrich_layer_satisfaction_from_evidence(
    context: dict[str, Any],
    *,
    evidence_decision: str | None,
    evidence_reason: str | None = None,
) -> dict[str, Any]:
    """Record an unsatisfied evidence layer after admissibility composition."""
    ctx = dict(context)
    metadata = strip_legacy_evidence_override(dict(ctx.get("metadata") or {}))
    satisfaction = dict(metadata.get("grant_layer_satisfaction") or {})
    if not satisfaction:
        ctx["metadata"] = metadata
        return ctx

    unsatisfied = [
        layer
        for layer in (satisfaction.get("unsatisfied_layers") or [])
        if layer.get("layer") != "evidence"
    ]
    if evidence_decision and evidence_decision not in (
        "allowed",
        "allowed_with_logging",
        "draft_only",
    ):
        unsatisfied.append(
            {
                "layer": "evidence",
                "decision": evidence_decision,
                "reason": evidence_reason
                or "Evidence layer remains independent of SCOPE grant authorization.",
            }
        )
    satisfaction["unsatisfied_layers"] = unsatisfied
    satisfaction["evidence_never_satisfied_by_grant"] = True
    # Ensure evidence never appears under satisfied_layers.
    satisfaction["satisfied_layers"] = [
        layer
        for layer in (satisfaction.get("satisfied_layers") or [])
        if layer.get("layer") in GRANT_SATISFIABLE_LAYERS
    ]
    metadata["grant_layer_satisfaction"] = satisfaction
    ctx["metadata"] = metadata
    return ctx
