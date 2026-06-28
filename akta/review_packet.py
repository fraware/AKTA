"""Human-readable review packet export and completed review import (v0.6)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from akta.hash import hash_object
from akta.records import validate_against_schema
from akta.scope_contract import extract_scope_fields, resolve_trigger_requested_scope


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def export_human_review_packet(
    review_trigger: dict[str, Any],
    *,
    record: dict[str, Any] | None = None,
    decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Export a human-readable review packet from an AKTA review trigger."""
    scope_fields = extract_scope_fields(review_trigger)
    requested_scope = scope_fields.get("requested_scope") or resolve_trigger_requested_scope(review_trigger)

    summary_lines = [
        f"Review required for tool: {review_trigger.get('requested_tool', 'unknown')}",
        f"Action: {review_trigger.get('requested_action', review_trigger.get('scientific_action_type', ''))}",
        f"Requested scope: {requested_scope}",
        f"Admissibility: {review_trigger.get('admissibility', '')}",
        f"Reason: {review_trigger.get('decision_reason', '')}",
    ]
    if review_trigger.get("consequentiality"):
        summary_lines.append(f"Consequential: {review_trigger.get('consequentiality_reason', 'yes')}")

    packet: dict[str, Any] = {
        "packet_type": "akta_human_review_packet",
        "schema_version": "akta-review-packet-v0.6",
        "review_trigger_id": review_trigger.get("review_trigger_id"),
        "akta_decision_id": review_trigger.get("akta_decision_id") or review_trigger.get("decision_id"),
        "akta_record_id": review_trigger.get("akta_record_id") or review_trigger.get("source_record_id"),
        "requested_scope": requested_scope,
        "required_review_role": review_trigger.get("required_review_role"),
        "blocked_tools": list(review_trigger.get("blocked_tools") or []),
        "allowed_next_steps": list(review_trigger.get("allowed_next_steps") or []),
        "human_summary": "\n".join(summary_lines),
        "scientific_context": review_trigger.get("scientific_context") or {},
        "policy_hash": review_trigger.get("policy_hash"),
        "exported_at": _utc_now_iso(),
    }

    if record is not None:
        packet["record_summary"] = {
            "record_id": record.get("record_id"),
            "record_hash": record.get("record_hash"),
            "classification": record.get("classification"),
            "decision": {
                "admissibility": (record.get("decision") or {}).get("admissibility"),
                "decision_reason": (record.get("decision") or {}).get("decision_reason"),
            },
        }
    if decision is not None:
        packet["decision_summary"] = {
            "decision_id": decision.get("decision_id"),
            "admissibility": decision.get("admissibility"),
            "scientific_action_type": decision.get("scientific_action_type"),
            "evidence_state": decision.get("evidence_state"),
        }

    packet["packet_hash"] = hash_object({k: v for k, v in packet.items() if k != "packet_hash"})
    return packet


def import_completed_review(
    packet_or_decision: dict[str, Any],
    *,
    validate: bool = True,
) -> dict[str, Any]:
    """Import a completed SCOPE/AKTA review decision into gate context metadata."""
    if packet_or_decision.get("decision") in ("approved", "denied", "deferred"):
        review_decision = packet_or_decision
    elif packet_or_decision.get("review_decision"):
        review_decision = packet_or_decision["review_decision"]
    else:
        raise ValueError("Input must be a review_decision artifact or wrapper containing review_decision")

    if validate:
        validate_against_schema(review_decision, "review_decision.schema.json")

    from akta.review_decision import apply_review_decision_to_context

    return apply_review_decision_to_context({}, review_decision)


def save_review_packet(packet: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(packet, indent=2), encoding="utf-8")
    return path


def load_review_packet(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
