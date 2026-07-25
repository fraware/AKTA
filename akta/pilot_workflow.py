"""Institutional pilot workflow stages and modes (P1-E / AS-05).

Five first-class PilotMode values with hard tool restrictions. Legacy
PilotStage / AKTA_PILOT_STAGE aliases map into modes; unknown values fail closed.

Beta scaffolding: does not certify production readiness.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from akta.records import validate_against_schema

_AKTA_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXCLUSIONS = _AKTA_ROOT / "policy" / "pilot_exclusions.yaml"
DEFAULT_MODE_DIR = _AKTA_ROOT / "policy" / "pilot_modes"


class PilotStage(str, Enum):
    """Deprecated stage aliases — prefer PilotMode."""

    SHADOW = "stage1_shadow"
    DRAFT_ONLY = "stage2_draft_only"
    VALIDATION = "stage3_validation"


class PilotMode(str, Enum):
    RETROSPECTIVE_RECONSTRUCTION = "retrospective_reconstruction"
    PROSPECTIVE_SHADOW = "prospective_shadow"
    READ_ONLY_SUPPORT = "read_only_support"
    EXECUTION_ADJACENT = "execution_adjacent"
    BOUNDED_EXECUTION = "bounded_execution"


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

STAGE_TO_MODE = {
    PilotStage.SHADOW: PilotMode.PROSPECTIVE_SHADOW,
    PilotStage.DRAFT_ONLY: PilotMode.READ_ONLY_SUPPORT,
    PilotStage.VALIDATION: PilotMode.BOUNDED_EXECUTION,
}

MODE_ALIASES: dict[str, PilotMode] = {
    m.value: m for m in PilotMode
}
# Legacy stage strings map into modes.
for _alias, _stage in STAGE_ALIASES.items():
    MODE_ALIASES[_alias] = STAGE_TO_MODE[_stage]
MODE_ALIASES.update(
    {
        "retrospective": PilotMode.RETROSPECTIVE_RECONSTRUCTION,
        "reconstruction": PilotMode.RETROSPECTIVE_RECONSTRUCTION,
        "prospective_shadow": PilotMode.PROSPECTIVE_SHADOW,
        "read_only": PilotMode.READ_ONLY_SUPPORT,
        "read_only_support": PilotMode.READ_ONLY_SUPPORT,
        "execution_adjacent": PilotMode.EXECUTION_ADJACENT,
        "bounded": PilotMode.BOUNDED_EXECUTION,
        "bounded_execution": PilotMode.BOUNDED_EXECUTION,
    }
)


@dataclass
class PilotGateResult:
    ok: bool
    stage: PilotStage
    mode: PilotMode | None = None
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


def resolve_pilot_mode(explicit: str | None = None) -> PilotMode:
    """Resolve pilot mode; fail closed on unknown values.

    Default without explicit mode / env preserves pre-AS-05 behavior:
    ``AKTA_PILOT_STAGE`` default ``stage1_shadow`` → ``prospective_shadow``.
    When neither ``AKTA_PILOT_MODE`` nor ``AKTA_PILOT_STAGE`` is set and
    ``explicit`` is None, returns ``prospective_shadow`` (stage1 mapping).
    """
    raw = (
        explicit
        or os.environ.get("AKTA_PILOT_MODE")
        or os.environ.get("AKTA_PILOT_STAGE")
        or "stage1_shadow"
    )
    key = str(raw).strip().lower()
    if key not in MODE_ALIASES:
        raise ValueError(f"unknown pilot mode: {raw}")
    return MODE_ALIASES[key]


def load_pilot_exclusions(path: str | Path | None = None) -> dict[str, Any]:
    exclusions_path = Path(path) if path else DEFAULT_EXCLUSIONS
    if not exclusions_path.is_file():
        return {"exclusions": []}
    return yaml.safe_load(exclusions_path.read_text(encoding="utf-8")) or {"exclusions": []}


def load_pilot_mode_profile(
    mode: PilotMode | str,
    *,
    modes_dir: str | Path | None = None,
    validate: bool = True,
) -> dict[str, Any]:
    resolved = mode if isinstance(mode, PilotMode) else resolve_pilot_mode(str(mode))
    directory = Path(modes_dir) if modes_dir else DEFAULT_MODE_DIR
    path = directory / f"{resolved.value}.yaml"
    if not path.is_file():
        raise ValueError(f"missing pilot mode profile: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if validate:
        validate_against_schema(data, "pilot_mode_profile.schema.json")
    return data


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


def mode_policy_switches(mode: PilotMode) -> dict[str, Any]:
    profile = load_pilot_mode_profile(mode)
    restrictions = dict(profile.get("restrictions") or {})
    return {
        "execute_actions": bool(restrictions.get("allow_live_tool_execution")),
        "persist_decisions": True,
        "allow_mutating_tools": bool(restrictions.get("allow_mutating_tools")),
        "allow_execution_tools": bool(restrictions.get("allow_execution_tools")),
        "allow_draft_tools": bool(restrictions.get("allow_draft_tools")),
        "shadow": bool(restrictions.get("shadow")),
        "operational_influence": bool(restrictions.get("operational_influence")),
        "require_stack_profile": bool(restrictions.get("require_stack_profile")),
        "require_trust_pins": bool(restrictions.get("require_trust_pins")),
        "require_scope_identity": mode == PilotMode.BOUNDED_EXECUTION,
        "require_signed_grant": mode == PilotMode.BOUNDED_EXECUTION,
        "require_full_grant_verification": mode == PilotMode.BOUNDED_EXECUTION,
        "require_pf_runtime_proof": mode == PilotMode.BOUNDED_EXECUTION,
        "require_pcs_package": mode == PilotMode.BOUNDED_EXECUTION,
        "require_transactional_ledger": mode == PilotMode.BOUNDED_EXECUTION,
        "tool_allowlist": list(restrictions.get("tool_allowlist") or []),
        "tool_denylist": list(restrictions.get("tool_denylist") or []),
        "denied_effect_classes": list(restrictions.get("denied_effect_classes") or []),
        "mode_label": mode.value,
        "profile": profile,
    }


def _tool_effect_class(tool_spec: Any) -> str:
    if tool_spec is None:
        return "unknown_tool"
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
    return "analysis_query"


def enforce_tool_for_mode(
    mode: PilotMode,
    *,
    requested_tool: str,
    tool_spec: Any = None,
) -> dict[str, Any] | None:
    """Return hard_block metadata when the tool violates mode restrictions."""
    switches = mode_policy_switches(mode)
    effect = _tool_effect_class(tool_spec)
    denylist = {t.lower() for t in switches.get("tool_denylist") or []}
    allowlist = [t.lower() for t in switches.get("tool_allowlist") or [] if t]
    denied_effects = set(switches.get("denied_effect_classes") or [])

    if requested_tool.lower() in denylist:
        return {
            "hard_block": True,
            "block_reason": f"pilot_mode_denylist:{mode.value}:{requested_tool}",
            "pilot_mode": mode.value,
            "shadow": switches["shadow"],
            "operational_influence": False,
        }

    if mode == PilotMode.BOUNDED_EXECUTION and allowlist:
        if requested_tool.lower() not in allowlist:
            return {
                "hard_block": True,
                "block_reason": f"pilot_mode_allowlist_miss:{mode.value}:{requested_tool}",
                "pilot_mode": mode.value,
                "shadow": False,
                "operational_influence": False,
            }

    if mode == PilotMode.RETROSPECTIVE_RECONSTRUCTION:
        return {
            "hard_block": True,
            "block_reason": "retrospective_reconstruction_forbids_live_tool_execution",
            "pilot_mode": mode.value,
            "shadow": False,
            "operational_influence": False,
        }

    if effect in denied_effects:
        return {
            "hard_block": True,
            "block_reason": f"pilot_mode_effect_denied:{mode.value}:{effect}",
            "pilot_mode": mode.value,
            "shadow": switches["shadow"],
            "operational_influence": False,
        }

    if not switches.get("allow_execution_tools") and effect in (
        "mutating_external",
        "mutating_internal",
        "unknown_tool",
    ):
        if mode in (
            PilotMode.PROSPECTIVE_SHADOW,
            PilotMode.READ_ONLY_SUPPORT,
            PilotMode.EXECUTION_ADJACENT,
            PilotMode.RETROSPECTIVE_RECONSTRUCTION,
        ):
            # execution_adjacent allows known draft/mutating_internal; not external/unknown exec
            if mode == PilotMode.EXECUTION_ADJACENT and effect == "mutating_internal":
                return None
            return {
                "hard_block": True,
                "block_reason": f"pilot_mode_execution_blocked:{mode.value}:{requested_tool}",
                "pilot_mode": mode.value,
                "shadow": switches["shadow"],
                "operational_influence": False,
            }


    return None


def apply_pilot_mode_to_evaluation(
    *,
    mode: PilotMode,
    requested_tool: str,
    tool_spec: Any = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return mode metadata; may include hard_block before tool side effects."""
    switches = mode_policy_switches(mode)
    meta: dict[str, Any] = {
        "pilot_mode": mode.value,
        "shadow": bool(switches.get("shadow")),
        "operational_influence": bool(switches.get("operational_influence")),
        "policy_switches": switches,
        "hard_block": False,
    }
    ctx = context or {}

    if mode == PilotMode.BOUNDED_EXECUTION:
        if switches.get("require_trust_pins"):
            trust_ok = bool(
                (ctx.get("metadata") or {}).get("trust_pins_ok")
                or ctx.get("trust_pins_ok")
                or (ctx.get("metadata") or {}).get("institutional_trust_ok")
            )
            if not trust_ok:
                meta.update(
                    {
                        "hard_block": True,
                        "block_reason": "bounded_execution_missing_trust_pins",
                        "operational_influence": False,
                    }
                )
                return meta
        if switches.get("require_stack_profile"):
            profile = ctx.get("stack_profile") or (ctx.get("metadata") or {}).get("stack_profile")
            if not profile:
                meta.update(
                    {
                        "hard_block": True,
                        "block_reason": "bounded_execution_missing_stack_profile",
                        "operational_influence": False,
                    }
                )
                return meta

    block = enforce_tool_for_mode(mode, requested_tool=requested_tool, tool_spec=tool_spec)
    if block:
        meta.update(block)
    return meta


def shadow_comparison_record(
    *,
    akta_decision: dict[str, Any],
    human_decision: str,
    notes: str = "",
) -> dict[str, Any]:
    """Comparison artifact for human vs AKTA shadow disagreement (feeds AS-07)."""
    return {
        "comparison_version": "akta-shadow-comparison-v1",
        "pilot_mode": PilotMode.PROSPECTIVE_SHADOW.value,
        "shadow": True,
        "operational_influence": False,
        "akta_admissibility": akta_decision.get("admissibility"),
        "human_decision": human_decision,
        "disagreement": akta_decision.get("admissibility") != human_decision,
        "decision_id": akta_decision.get("decision_id"),
        "notes": notes,
    }


def evaluate_pilot_gate(
    *,
    stage: str | PilotStage | None = None,
    mode: str | PilotMode | None = None,
    requested_tool: str | None = None,
    requested_action: str | None = None,
    metadata: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    exclusions_path: str | Path | None = None,
) -> PilotGateResult:
    """Fail-closed pilot stage/mode gate.

    Stage 3 / bounded_execution requires real SCOPE identity, signed grant,
    full grant verification, PF runtime proof, PCS package, and transactional
    ledger evidence.
    """
    resolved_mode: PilotMode | None = None
    if mode is not None:
        resolved_mode = mode if isinstance(mode, PilotMode) else resolve_pilot_mode(str(mode))
        # Map mode back to closest legacy stage for compatibility fields.
        if resolved_mode == PilotMode.BOUNDED_EXECUTION:
            resolved_stage = PilotStage.VALIDATION
        elif resolved_mode in (PilotMode.READ_ONLY_SUPPORT, PilotMode.EXECUTION_ADJACENT):
            resolved_stage = PilotStage.DRAFT_ONLY
        else:
            resolved_stage = PilotStage.SHADOW
        switches = mode_policy_switches(resolved_mode)
    else:
        resolved_stage = stage if isinstance(stage, PilotStage) else resolve_pilot_stage(
            stage if isinstance(stage, str) else None
        )
        resolved_mode = STAGE_TO_MODE[resolved_stage]
        switches = stage_policy_switches(resolved_stage)
        # Prefer mode switches when profiles exist.
        try:
            switches = {**switches, **mode_policy_switches(resolved_mode)}
        except ValueError:
            pass

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
    if resolved_stage == PilotStage.DRAFT_ONLY or resolved_mode in (
        PilotMode.READ_ONLY_SUPPORT,
        PilotMode.EXECUTION_ADJACENT,
    ):
        mutates = bool((metadata or {}).get("mutates_state"))
        if mutates or (requested_tool and "robot" in requested_tool.lower()):
            if resolved_mode != PilotMode.EXECUTION_ADJACENT or "robot" in (
                requested_tool or ""
            ).lower():
                errors.append("pilot_mode rejects mutating / robot tools without authorization")

    if resolved_stage == PilotStage.VALIDATION or resolved_mode == PilotMode.BOUNDED_EXECUTION:
        required = {
            "scope_identity": switches.get("require_scope_identity"),
            "signed_grant": switches.get("require_signed_grant"),
            "full_grant_verification": switches.get("require_full_grant_verification"),
            "pf_runtime_proof": switches.get("require_pf_runtime_proof"),
            "pcs_package": switches.get("require_pcs_package"),
            "transactional_ledger": switches.get("require_transactional_ledger"),
        }
        for key, needed in required.items():
            if needed and not ev.get(key):
                errors.append(f"bounded_execution missing required evidence:{key}")

    if resolved_mode == PilotMode.PROSPECTIVE_SHADOW or resolved_stage == PilotStage.SHADOW:
        warnings.append("shadow mode: decisions logged only; no execution")
        switches["operational_influence"] = False
        switches["shadow"] = True

    return PilotGateResult(
        ok=not errors,
        stage=resolved_stage,
        mode=resolved_mode,
        errors=errors,
        warnings=warnings,
        exclusions_hit=hits,
        policy_switches=switches,
    )


__all__ = [
    "MODE_ALIASES",
    "PilotGateResult",
    "PilotMode",
    "PilotStage",
    "STAGE_TO_MODE",
    "apply_pilot_mode_to_evaluation",
    "enforce_tool_for_mode",
    "evaluate_pilot_gate",
    "load_pilot_exclusions",
    "load_pilot_mode_profile",
    "mode_policy_switches",
    "resolve_pilot_mode",
    "resolve_pilot_stage",
    "shadow_comparison_record",
    "stage_policy_switches",
]
