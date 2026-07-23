"""Institutional pilot workflow stages (P1-E).

Stage 1 Shadow — observe/log only
Stage 2 Draft-only — non-mutating drafts
Stage 3 Validation — full trust-stack required; fail closed if any missing

Beta scaffolding: does not certify production readiness.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

_AKTA_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXCLUSIONS = _AKTA_ROOT / "policy" / "pilot_exclusions.yaml"


class PilotStage(str, Enum):
    SHADOW = "stage1_shadow"
    DRAFT_ONLY = "stage2_draft_only"
    VALIDATION = "stage3_validation"


STAGE_ALIASES = {
    "1": PilotStage.SHADOW,
    "shadow": PilotStage.SHADOW,
    "stage1": PilotStage.SHADOW,
    "stage1_shadow": PilotStage.SHADOW,
    "2": PilotStage.DRAFT_ONLY,
    "draft": PilotStage.DRAFT_ONLY,
    "draft_only": PilotStage.DRAFT_ONLY,
    "stage2": PilotStage.DRAFT_ONLY,
    "stage2_draft_only": PilotStage.DRAFT_ONLY,
    "3": PilotStage.VALIDATION,
    "validation": PilotStage.VALIDATION,
    "stage3": PilotStage.VALIDATION,
    "stage3_validation": PilotStage.VALIDATION,
}


@dataclass
class PilotGateResult:
    ok: bool
    stage: PilotStage
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    exclusions_hit: list[str] = field(default_factory=list)
    policy_switches: dict[str, Any] = field(default_factory=dict)
    beta: bool = True


def resolve_pilot_stage(explicit: str | None = None) -> PilotStage:
    raw = (explicit or os.environ.get("AKTA_PILOT_STAGE") or "stage1_shadow").strip().lower()
    if raw not in STAGE_ALIASES:
        raise ValueError(f"unknown pilot stage: {raw}")
    return STAGE_ALIASES[raw]


def load_pilot_exclusions(path: str | Path | None = None) -> dict[str, Any]:
    exclusions_path = Path(path) if path else DEFAULT_EXCLUSIONS
    if not exclusions_path.is_file():
        return {"exclusions": []}
    return yaml.safe_load(exclusions_path.read_text(encoding="utf-8")) or {"exclusions": []}


def _exclusion_hits(
    *,
    requested_tool: str | None,
    requested_action: str | None,
    metadata: dict[str, Any] | None,
    exclusions: dict[str, Any],
) -> list[str]:
    hits: list[str] = []
    meta = metadata or {}
    blob = " ".join(
        str(x).lower()
        for x in (
            requested_tool,
            requested_action,
            meta.get("domain"),
            meta.get("hazard_class"),
            meta.get("publication_claim"),
            *(meta.get("tags") or []),
        )
        if x
    )
    for entry in exclusions.get("exclusions") or []:
        if not isinstance(entry, dict):
            continue
        eid = str(entry.get("id") or entry.get("name") or "exclusion")
        keywords = [str(k).lower() for k in (entry.get("keywords") or [])]
        if any(k and k in blob for k in keywords):
            hits.append(eid)
        flag = entry.get("metadata_flag")
        if flag and meta.get(flag):
            hits.append(eid)
    return sorted(set(hits))


def stage_policy_switches(stage: PilotStage) -> dict[str, Any]:
    if stage == PilotStage.SHADOW:
        return {
            "execute_actions": False,
            "persist_decisions": True,
            "allow_mutating_tools": False,
            "allow_draft_tools": False,
            "require_scope_identity": False,
            "require_signed_grant": False,
            "require_pf_runtime_proof": False,
            "require_pcs_package": False,
            "require_transactional_ledger": False,
            "mode_label": "shadow",
        }
    if stage == PilotStage.DRAFT_ONLY:
        return {
            "execute_actions": False,
            "persist_decisions": True,
            "allow_mutating_tools": False,
            "allow_draft_tools": True,
            "require_scope_identity": False,
            "require_signed_grant": False,
            "require_pf_runtime_proof": False,
            "require_pcs_package": False,
            "require_transactional_ledger": False,
            "mode_label": "draft_only",
        }
    return {
        "execute_actions": True,
        "persist_decisions": True,
        "allow_mutating_tools": True,
        "allow_draft_tools": True,
        "require_scope_identity": True,
        "require_signed_grant": True,
        "require_full_grant_verification": True,
        "require_pf_runtime_proof": True,
        "require_pcs_package": True,
        "require_transactional_ledger": True,
        "mode_label": "validation",
    }


def evaluate_pilot_gate(
    *,
    stage: str | PilotStage | None = None,
    requested_tool: str | None = None,
    requested_action: str | None = None,
    metadata: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    exclusions_path: str | Path | None = None,
) -> PilotGateResult:
    """Fail-closed pilot stage gate.

    Stage 3 requires real SCOPE identity, signed grant, full grant verification,
    PF runtime proof, PCS package, and transactional ledger evidence.
    """
    resolved = stage if isinstance(stage, PilotStage) else resolve_pilot_stage(
        stage if isinstance(stage, str) else None
    )
    switches = stage_policy_switches(resolved)
    exclusions = load_pilot_exclusions(exclusions_path)
    hits = _exclusion_hits(
        requested_tool=requested_tool,
        requested_action=requested_action,
        metadata=metadata,
        exclusions=exclusions,
    )
    errors: list[str] = []
    warnings: list[str] = []
    if hits:
        errors.append(f"pilot_exclusion:{','.join(hits)}")

    ev = evidence or {}
    if resolved == PilotStage.DRAFT_ONLY:
        mutates = bool((metadata or {}).get("mutates_state"))
        if mutates or (requested_tool and "robot" in requested_tool.lower()):
            errors.append("stage2_draft_only rejects mutating / robot tools")

    if resolved == PilotStage.VALIDATION:
        required = {
            "scope_identity": switches["require_scope_identity"],
            "signed_grant": switches["require_signed_grant"],
            "full_grant_verification": switches["require_full_grant_verification"],
            "pf_runtime_proof": switches["require_pf_runtime_proof"],
            "pcs_package": switches["require_pcs_package"],
            "transactional_ledger": switches["require_transactional_ledger"],
        }
        for key, needed in required.items():
            if needed and not ev.get(key):
                errors.append(f"stage3_validation missing required evidence:{key}")

    if resolved == PilotStage.SHADOW:
        warnings.append("shadow mode: decisions logged only; no execution")

    return PilotGateResult(
        ok=not errors,
        stage=resolved,
        errors=errors,
        warnings=warnings,
        exclusions_hit=hits,
        policy_switches=switches,
    )


__all__ = [
    "PilotGateResult",
    "PilotStage",
    "evaluate_pilot_gate",
    "load_pilot_exclusions",
    "resolve_pilot_stage",
    "stage_policy_switches",
]
