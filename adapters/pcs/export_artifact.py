"""Export PCS-compatible AKTA artifact bundle (v0.5 full chain)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from akta.hash import hash_file_content, hash_object
from akta.records import validate_against_schema


PCS_SCHEMA_VERSION = "akta-record-v0.5"

CORE_FILES = [
    "akta_record.json",
    "akta_decision.json",
    "policy_hash.txt",
    "domain_overlay_hash.txt",
    "tool_registry_hash.txt",
]

OPTIONAL_ARTIFACTS = [
    "vsa_report.json",
]


def build_pcs_manifest(
    record: dict[str, Any],
    decision: dict[str, Any] | None = None,
    *,
    file_hashes: dict[str, str] | None = None,
    include_review_trigger: bool = False,
    include_scope_packet: bool = False,
    include_scope_decision: bool = False,
    include_scope_grant: bool = False,
    include_pf_obligation: bool = False,
    include_vsa_report: bool = False,
) -> dict[str, Any]:
    """Build PCS manifest v0.5 from record and optional chain artifacts."""
    provenance = record.get("provenance", {})
    files = list(CORE_FILES)
    if include_review_trigger:
        files.append("review_trigger.json")
    if include_scope_packet:
        files.append("scope_review_packet.json")
    if include_scope_decision:
        files.append("scope_decision.json")
    if include_scope_grant:
        files.append("scope_grant.json")
    if include_pf_obligation:
        files.append("pf_obligation.json")
    if include_vsa_report:
        files.append("vsa_report.json")

    manifest: dict[str, Any] = {
        "artifact_type": "akta_scientific_action_record",
        "schema_version": PCS_SCHEMA_VERSION,
        "record_hash": record.get("record_hash"),
        "policy_hash": provenance.get("policy_hash"),
        "integrity_mode": provenance.get("integrity_mode"),
        "domain_overlay_hash": provenance.get("domain_overlay_hash"),
        "tool_registry_hash": provenance.get("tool_registry_hash"),
        "decision_id": (decision or {}).get("decision_id") or record.get("record_id", "").replace("SAR", "DEC"),
        "files": sorted(files + ["manifest.json"]),
    }
    if file_hashes:
        manifest["file_hashes"] = {k: v for k, v in sorted(file_hashes.items()) if k != "manifest.json"}

    manifest["manifest_hash"] = hash_object(
        {k: v for k, v in manifest.items() if k not in ("manifest_hash", "file_hashes")}
        | {"files": sorted(files)}
        | ({"file_hashes": manifest.get("file_hashes")} if manifest.get("file_hashes") else {})
    )
    return manifest


def validate_pcs_bundle(bundle_dir: str | Path) -> None:
    """Verify PCS bundle file hashes match manifest (tamper detection)."""
    bundle_dir = Path(bundle_dir)
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"PCS bundle missing manifest.json: {bundle_dir}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    file_hashes = manifest.get("file_hashes")
    if not file_hashes:
        raise ValueError("PCS manifest missing file_hashes (v0.5 required)")

    listed = set(manifest.get("files", []))
    if listed != set(file_hashes.keys()) | {"manifest.json"}:
        raise ValueError("PCS manifest files list does not match file_hashes keys")

    for fname, expected_hash in file_hashes.items():
        fpath = bundle_dir / fname
        if not fpath.exists():
            raise ValueError(f"PCS bundle missing listed artifact: {fname}")
        actual = hash_file_content(fpath.read_text(encoding="utf-8"))
        if actual != expected_hash:
            raise ValueError(
                f"PCS bundle tamper detected for {fname}: expected {expected_hash}, got {actual}"
            )

    stored_manifest_hash = manifest.get("manifest_hash")
    recomputed = build_pcs_manifest(
        json.loads((bundle_dir / "akta_record.json").read_text(encoding="utf-8")),
        json.loads((bundle_dir / "akta_decision.json").read_text(encoding="utf-8")),
        file_hashes=file_hashes,
        include_review_trigger=(bundle_dir / "review_trigger.json").exists(),
        include_scope_packet=(bundle_dir / "scope_review_packet.json").exists(),
        include_scope_decision=(bundle_dir / "scope_decision.json").exists(),
        include_scope_grant=(bundle_dir / "scope_grant.json").exists(),
        include_pf_obligation=(bundle_dir / "pf_obligation.json").exists(),
        include_vsa_report=(bundle_dir / "vsa_report.json").exists(),
    )
    if stored_manifest_hash != recomputed["manifest_hash"]:
        raise ValueError("PCS manifest_hash does not match recomputed hash")


def export_pcs_bundle(
    record: Any,
    out_dir: str | Path,
    *,
    decision: dict[str, Any] | None = None,
    scope_review_packet: dict[str, Any] | None = None,
    scope_decision: dict[str, Any] | None = None,
    scope_grant: dict[str, Any] | None = None,
    pf_obligation: dict[str, Any] | None = None,
    vsa_report: dict[str, Any] | None = None,
    validate: bool = True,
) -> Path:
    """Export AKTA Record as PCS-compatible artifact bundle with full chain."""
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

    if validate and scope_grant is not None:
        from akta.scope_contract import (
            _scope_grant_approved_scope,
            _scope_grant_requested_scope,
            validate_approval_grant,
        )

        granted = _scope_grant_approved_scope(scope_grant) or ""
        requested = (
            _scope_grant_requested_scope(
                scope_grant,
                data,
                data.get("review_trigger"),
            )
            or ""
        )
        if granted and requested:
            try:
                validate_approval_grant(granted_scope=granted, requested_scope=requested)
            except ValueError as exc:
                raise ValueError(f"Invalid SCOPE grant blocks PCS export: {exc}") from exc

    artifacts: dict[str, str] = {}

    def _write(name: str, content: str) -> None:
        (out_dir / name).write_text(content, encoding="utf-8")
        artifacts[name] = hash_file_content(content)

    _write("akta_record.json", json.dumps(data, indent=2))
    _write("akta_decision.json", json.dumps(decision_payload, indent=2))
    _write("policy_hash.txt", provenance.get("policy_hash", ""))
    _write("domain_overlay_hash.txt", provenance.get("domain_overlay_hash") or "")
    _write("tool_registry_hash.txt", provenance.get("tool_registry_hash", ""))

    review_trigger = data.get("review_trigger")
    has_review_trigger = review_trigger is not None
    if review_trigger:
        _write("review_trigger.json", json.dumps(review_trigger, indent=2))

    has_scope_packet = scope_review_packet is not None
    if scope_review_packet is not None:
        _write("scope_review_packet.json", json.dumps(scope_review_packet, indent=2))

    has_scope_decision = scope_decision is not None
    if scope_decision is not None:
        _write("scope_decision.json", json.dumps(scope_decision, indent=2))

    has_scope_grant = scope_grant is not None
    if scope_grant is not None:
        _write("scope_grant.json", json.dumps(scope_grant, indent=2))

    has_pf = pf_obligation is not None
    if pf_obligation is not None:
        _write("pf_obligation.json", json.dumps(pf_obligation, indent=2))

    has_vsa = vsa_report is not None
    if vsa_report is None:
        ctx_vsa = (data.get("context") or {}).get("vsa_report")
        if isinstance(ctx_vsa, dict):
            vsa_report = ctx_vsa
            has_vsa = True
    if vsa_report is not None:
        _write("vsa_report.json", json.dumps(vsa_report, indent=2))

    manifest = build_pcs_manifest(
        data,
        decision_payload,
        file_hashes=artifacts,
        include_review_trigger=has_review_trigger,
        include_scope_packet=has_scope_packet,
        include_scope_decision=has_scope_decision,
        include_scope_grant=has_scope_grant,
        include_pf_obligation=has_pf,
        include_vsa_report=has_vsa,
    )
    manifest_content = json.dumps(manifest, indent=2)
    (out_dir / "manifest.json").write_text(manifest_content, encoding="utf-8")

    if validate:
        validate_against_schema(manifest, "pcs_akta_artifact.schema.json")
        validate_pcs_bundle(out_dir)

    return out_dir
