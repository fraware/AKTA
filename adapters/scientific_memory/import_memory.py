"""Scientific Memory adapter — import/export bounded memory entries (v0.6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from akta.hash import hash_object


def import_from_pcs_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    """Import bounded results + admissibility history from a PCS bundle."""
    bundle_dir = Path(bundle_dir)
    record = json.loads((bundle_dir / "akta_record.json").read_text(encoding="utf-8"))
    decision_path = bundle_dir / "akta_decision.json"
    decision = (
        json.loads(decision_path.read_text(encoding="utf-8"))
        if decision_path.exists()
        else record.get("decision", {})
    )

    classification = record.get("classification", {})
    record_decision = record.get("decision", decision)

    entry: dict[str, Any] = {
        "entry_type": "scientific_memory_import",
        "schema_version": "akta-scientific-memory-v0.6",
        "source_record_id": record.get("record_id"),
        "source_record_hash": record.get("record_hash"),
        "admissibility": record_decision.get("admissibility"),
        "scientific_action_type": classification.get("scientific_action_type"),
        "evidence_state": classification.get("evidence_state"),
        "validation_status": classification.get("validation_status"),
        "decision_reason": record_decision.get("decision_reason"),
        "policy_hash": (record.get("provenance") or {}).get("policy_hash"),
        "bounded_claims": _extract_bounded_claims(record),
        "admissibility_history": [
            {
                "admissibility": record_decision.get("admissibility"),
                "timestamp": record.get("timestamp"),
                "decision_id": decision.get("decision_id") if isinstance(decision, dict) else None,
            }
        ],
    }

    manifest_path = bundle_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry["pcs_manifest_hash"] = manifest.get("manifest_hash")

    entry["entry_hash"] = hash_object({k: v for k, v in entry.items() if k != "entry_hash"})
    return entry


def import_from_record(record: dict[str, Any]) -> dict[str, Any]:
    """Import memory entry shape from a standalone AKTA record."""
    classification = record.get("classification", {})
    record_decision = record.get("decision", {})
    result: dict[str, Any] = {
        "entry_type": "scientific_memory_import",
        "schema_version": "akta-scientific-memory-v0.6",
        "source_record_id": record.get("record_id"),
        "source_record_hash": record.get("record_hash"),
        "admissibility": record_decision.get("admissibility"),
        "scientific_action_type": classification.get("scientific_action_type"),
        "evidence_state": classification.get("evidence_state"),
        "validation_status": classification.get("validation_status"),
        "decision_reason": record_decision.get("decision_reason"),
        "policy_hash": (record.get("provenance") or {}).get("policy_hash"),
        "bounded_claims": _extract_bounded_claims(record),
        "admissibility_history": [
            {
                "admissibility": record_decision.get("admissibility"),
                "timestamp": record.get("timestamp"),
            }
        ],
    }
    result["entry_hash"] = hash_object({k: v for k, v in result.items() if k != "entry_hash"})
    return result


def _extract_bounded_claims(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract bounded claim summaries from record context / VSA report."""
    claims: list[dict[str, Any]] = []
    ctx = record.get("context") or {}
    vsa = ctx.get("vsa_report") or record.get("integrations", {}).get("vsa_report")
    if isinstance(vsa, dict):
        for claim in vsa.get("claims") or []:
            if isinstance(claim, dict):
                claims.append({
                    "claim_id": claim.get("claim_id"),
                    "text": (claim.get("text") or "")[:500],
                    "evidence_level": claim.get("evidence_level"),
                    "confidence": claim.get("confidence"),
                })
    summary = record.get("ai_output_summary") or ctx.get("summary")
    if summary and not claims:
        claims.append({"claim_id": "summary", "text": str(summary)[:500], "evidence_level": "derived"})
    return claims[:10]


def export_memory_entry(entry: dict[str, Any], out_path: str | Path) -> Path:
    """Write scientific memory entry JSON."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
    return out_path
