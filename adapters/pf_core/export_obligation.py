"""Export PF-Core runtime obligation from AKTA Record."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from akta.hash import hash_object
from akta.records import validate_against_schema


def _hash_field(value: str) -> str:
    return hash_object({"value": value})


def _obligation_type(admissibility: str) -> str:
    mapping = {
        "blocked": "tool_block",
        "abstain_insufficient_context": "tool_block",
        "review_required": "tool_review",
        "authorization_required": "tool_authorize",
        "draft_only": "tool_review",
    }
    return mapping.get(admissibility, "tool_allow")


def _enforcement_mode(admissibility: str) -> str:
    if admissibility in ("blocked", "abstain_insufficient_context"):
        return "hard_block"
    if admissibility == "authorization_required":
        return "authorization_gate"
    if admissibility in ("review_required", "draft_only"):
        return "review_gate"
    return "log_and_allow"


def _runtime_behavior(admissibility: str, blocked_tools: list[str], allowed_tools: list[str]) -> dict[str, Any]:
    return {
        "block_execution": admissibility in ("blocked", "abstain_insufficient_context"),
        "require_review_before_tool_call": admissibility in ("review_required", "draft_only"),
        "require_authorization_before_tool_call": admissibility == "authorization_required",
        "blocked_tools": blocked_tools,
        "allowed_tools": allowed_tools,
        "log_all_tool_calls": admissibility in ("allowed_with_logging", "allowed"),
    }


def build_pf_obligation(record: dict[str, Any], decision_id: str | None = None) -> dict[str, Any]:
    """Build PF-Core obligation JSON from an AKTA Record."""
    decision = record.get("decision", {})
    classification = record.get("classification", {})
    provenance = record.get("provenance", {})
    admissibility = decision.get("admissibility", "blocked")
    blocked = decision.get("blocked_tools", [])
    allowed = decision.get("allowed_tools", [])

    obligation = {
        "obligation_id": f"PF-OBL-{record.get('record_id', 'UNKNOWN')}",
        "obligation_type": _obligation_type(admissibility),
        "source": "AKTA",
        "source_record_id": record.get("record_id"),
        "decision_id": decision_id or record.get("record_id", "").replace("SAR", "DEC"),
        "decision": admissibility,
        "decision_reason_hash": _hash_field(decision.get("decision_reason", "")),
        "blocked_tools": blocked,
        "allowed_tools": allowed,
        "max_responsibility_level": classification.get("responsibility_level"),
        "policy_hash": provenance.get("policy_hash"),
        "tool_registry_hash": provenance.get("tool_registry_hash"),
        "domain_overlay_hash": provenance.get("domain_overlay_hash"),
        "scope_grant_ref": record.get("integrations", {}).get("scope_grant_ref"),
        "review_trigger_id": (record.get("review_trigger") or {}).get("review_trigger_id"),
        "expires_at": (record.get("review_trigger") or {}).get("expires_at"),
        "enforcement_mode": _enforcement_mode(admissibility),
        "required_runtime_behavior": _runtime_behavior(admissibility, blocked, allowed),
        "next_admissible_steps": decision.get("next_admissible_steps", []),
        "required_review_role": decision.get("required_review_role"),
        "consequentiality": decision.get("consequentiality", False),
    }
    obligation["obligation_hash"] = hash_object(
        {k: v for k, v in obligation.items() if k != "obligation_hash"}
    )
    return obligation


def export_pf_obligation(
    record: Any,
    out_dir: str | Path,
    *,
    validate: bool = True,
    decision_id: str | None = None,
) -> Path:
    """Write PF-Core obligation to output directory."""
    from akta.records import AKTARecord

    data = record.data if isinstance(record, AKTARecord) else record
    obligation = build_pf_obligation(data, decision_id=decision_id)
    if validate:
        validate_against_schema(obligation, "pf_core_obligation.schema.json")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record_id = data.get("record_id", "unknown")
    path = out_dir / f"pf_obligation_{record_id}.json"
    path.write_text(json.dumps(obligation, indent=2), encoding="utf-8")
    return path
