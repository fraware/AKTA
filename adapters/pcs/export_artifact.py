"""Export PCS-compatible AKTA artifact bundle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from akta.hash import hash_object
from akta.records import validate_against_schema


def build_pcs_manifest(record: dict[str, Any], decision: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build PCS manifest from record and optional full decision."""
    provenance = record.get("provenance", {})
    files = [
        "akta_record.json",
        "akta_decision.json",
        "policy_hash.txt",
        "domain_overlay_hash.txt",
        "tool_registry_hash.txt",
    ]
    if record.get("review_trigger"):
        files.append("review_trigger.json")

    manifest = {
        "artifact_type": "akta_scientific_action_record",
        "schema_version": "akta-record-v0.2",
        "record_hash": record.get("record_hash"),
        "policy_hash": provenance.get("policy_hash"),
        "domain_overlay_hash": provenance.get("domain_overlay_hash"),
        "tool_registry_hash": provenance.get("tool_registry_hash"),
        "decision_id": (decision or {}).get("decision_id") or record.get("record_id", "").replace("SAR", "DEC"),
        "files": files + ["manifest.json"],
    }
    manifest["manifest_hash"] = hash_object(
        {k: v for k, v in manifest.items() if k not in ("manifest_hash", "files")}
        | {"files": sorted(files)}
    )
    return manifest


def export_pcs_bundle(
    record: Any,
    out_dir: str | Path,
    *,
    decision: dict[str, Any] | None = None,
    validate: bool = True,
) -> Path:
    """Export AKTA Record as PCS-compatible artifact bundle."""
    from akta.records import AKTARecord

    data = record.data if isinstance(record, AKTARecord) else record
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    provenance = data.get("provenance", {})
    decision_payload = decision or {
        "decision_id": data.get("record_id", "").replace("SAR", "DEC"),
        "admissibility": data["decision"]["admissibility"],
        "scientific_action_type": data["classification"]["scientific_action_type"],
        "responsibility_level": data["classification"]["responsibility_level"],
        "evidence_state": data["classification"]["evidence_state"],
        "decision_reason": data["decision"]["decision_reason"],
        "policy_hash": provenance.get("policy_hash"),
        "consequentiality": data["decision"].get("consequentiality", False),
    }

    if validate and not provenance.get("policy_hash", "").startswith("sha256:"):
        raise ValueError("PCS export requires valid policy_hash on record provenance")

    manifest = build_pcs_manifest(data, decision_payload)

    (out_dir / "akta_record.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (out_dir / "akta_decision.json").write_text(json.dumps(decision_payload, indent=2), encoding="utf-8")
    (out_dir / "policy_hash.txt").write_text(provenance.get("policy_hash", ""), encoding="utf-8")
    (out_dir / "domain_overlay_hash.txt").write_text(
        provenance.get("domain_overlay_hash") or "", encoding="utf-8"
    )
    (out_dir / "tool_registry_hash.txt").write_text(
        provenance.get("tool_registry_hash", ""), encoding="utf-8"
    )

    review_trigger = data.get("review_trigger")
    if review_trigger:
        (out_dir / "review_trigger.json").write_text(json.dumps(review_trigger, indent=2), encoding="utf-8")

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if validate:
        validate_against_schema(manifest, "pcs_akta_artifact.schema.json")

    return out_dir
