"""SCOPE grant override policy — explicit evidence-layer satisfaction rules (v1.0)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_AKTA_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_RULES_PATH = _AKTA_ROOT / "policy" / "scope_grant_override_rules.yaml"


def _evidence_rank(evidence_state: str) -> int:
    if evidence_state.startswith("E") and len(evidence_state) > 1 and evidence_state[1].isdigit():
        return int(evidence_state[1])
    return 0


@lru_cache(maxsize=4)
def load_grant_override_rules(rules_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(rules_path) if rules_path else _DEFAULT_RULES_PATH
    if not path.is_file():
        return {"default": "evidence_and_profile_not_satisfied_by_grant", "rules": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data


def grant_may_satisfy_evidence(
    *,
    deployment_profile: str,
    evidence_state: str,
    rules_path: str | Path | None = None,
) -> bool:
    """Return True when an explicit policy rule allows grant to satisfy evidence layer."""
    rules_doc = load_grant_override_rules(rules_path)
    cur_rank = _evidence_rank(evidence_state)
    for rule in rules_doc.get("rules") or []:
        if rule.get("profile") != deployment_profile:
            continue
        min_evidence = rule.get("evidence_min", "")
        min_rank = _evidence_rank(str(min_evidence))
        if cur_rank >= min_rank:
            return bool(rule.get("grant_may_satisfy_evidence_layer", False))
    return False


def apply_grant_override_metadata(
    context: dict[str, Any],
    *,
    deployment_profile: str,
    evidence_state: str,
    rules_path: str | Path | None = None,
) -> dict[str, Any]:
    """Set scope_grant_satisfies_evidence when policy explicitly permits override."""
    ctx = dict(context)
    metadata = dict(ctx.get("metadata") or {})
    if grant_may_satisfy_evidence(
        deployment_profile=deployment_profile,
        evidence_state=evidence_state,
        rules_path=rules_path,
    ):
        metadata["scope_grant_satisfies_evidence"] = True
    else:
        metadata.pop("scope_grant_satisfies_evidence", None)
    ctx["metadata"] = metadata
    return ctx
