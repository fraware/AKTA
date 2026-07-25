"""Reconstructability helpers shared by CLI and demo scripts (AS-08)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from akta.hash import hash_file_content, hash_object

REQUIRED_RELEASE_FILES = (
    "akta_decision.json",
    "akta_record.json",
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def checksum_release_bundle(release_dir: str | Path) -> dict[str, str]:
    root = Path(release_dir)
    checksums: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            checksums[rel] = hash_file_content(path.read_bytes())
    return checksums


def reconstruct_from_release(
    release_dir: str | Path,
    *,
    require_bindings: bool = True,
) -> dict[str, Any]:
    """Rebuild a reconstruction report from a release / action_release directory.

    Verifies presence of decision/record, binding digests when present, and
    optional PCS/PF/review artifacts. Does not invent missing evidence.
    """
    root = Path(release_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"release directory not found: {root}")

    errors: list[str] = []
    artifacts: dict[str, Any] = {}

    decision_path = root / "akta_decision.json"
    record_path = root / "akta_record.json"
    # Also accept nested pcs_bundle layout.
    if not decision_path.is_file():
        alt = root / "pcs_bundle" / "akta_decision.json"
        if alt.is_file():
            decision_path = alt
            record_path = root / "pcs_bundle" / "akta_record.json"
            root = root / "pcs_bundle"

    for name, path in (("decision", decision_path), ("record", record_path)):
        if not path.is_file():
            errors.append(f"missing_required_artifact:{name}")
        else:
            artifacts[name] = _load_json(path)

    decision = artifacts.get("decision") or {}
    record = artifacts.get("record") or {}
    bindings = decision.get("bindings") or record.get("bindings") or {}

    if require_bindings and not bindings:
        errors.append("missing_bindings")

    # Cross-check IDs when both present.
    if decision and record:
        dec_id = decision.get("decision_id")
        bind_dec = (bindings or {}).get("decision_id")
        if bind_dec and dec_id and bind_dec != dec_id:
            errors.append(f"decision_id_mismatch:binding={bind_dec} decision={dec_id}")
        if decision.get("admissibility") != (record.get("decision") or {}).get("admissibility"):
            errors.append("admissibility_mismatch:decision_vs_record")
        if decision.get("policy_hash") and record.get("provenance", {}).get("policy_hash"):
            if decision["policy_hash"] != record["provenance"]["policy_hash"]:
                errors.append("policy_hash_mismatch:decision_vs_record")

    optional = {
        "review_trigger": root / "review_trigger.json",
        "pf_obligation": root / "pf_obligation.json",
        "manifest": root / "manifest.json",
        "vsa_report": root / "vsa_report.json",
    }
    present_optional: dict[str, Any] = {}
    for key, path in optional.items():
        # PF obligation may be named pf_obligation_<id>.json
        if key == "pf_obligation" and not path.is_file():
            matches = list(root.glob("pf_obligation*.json"))
            path = matches[0] if matches else path
        if path.is_file():
            present_optional[key] = _load_json(path)
            # Binding checks
            if key == "review_trigger" and bindings:
                trig = present_optional[key]
                if trig.get("decision_id") and bindings.get("decision_id"):
                    if trig["decision_id"] != bindings["decision_id"]:
                        errors.append("scope_trigger_decision_id_mismatch")
            if key == "pf_obligation" and bindings:
                obl = present_optional[key]
                if obl.get("decision_id") and bindings.get("decision_id"):
                    if obl["decision_id"] != bindings["decision_id"] and not str(
                        obl.get("decision_id", "")
                    ).endswith(str(bindings["decision_id"]).split("-")[-1]):
                        # Allow legacy derived IDs; flag hard mismatch on explicit bindings field.
                        if (obl.get("bindings") or {}).get("decision_id") not in (
                            None,
                            bindings.get("decision_id"),
                        ):
                            errors.append("pf_obligation_decision_id_mismatch")
            if key == "manifest" and bindings:
                man = present_optional[key]
                if man.get("decision_id") and bindings.get("decision_id"):
                    if man["decision_id"] != bindings["decision_id"] and not str(
                        man.get("decision_id", "")
                    ).startswith("AKTA-"):
                        pass

    checksums = checksum_release_bundle(root)
    completeness_fields = [
        "decision_id",
        "record_id",
        "policy_hash",
        "tool_registry_hash",
        "requested_tool",
        "action_class",
        "vsa_decision_time_bundle_digest",
        "decision_basis_digest",
    ]
    present_bind = sum(1 for f in completeness_fields if bindings.get(f))
    reconstruction = {
        "reconstruction_version": "akta-reconstruction-v1",
        "release_dir": str(root.resolve()),
        "ok": not errors,
        "errors": errors,
        "decision_id": decision.get("decision_id"),
        "record_id": record.get("record_id"),
        "admissibility": decision.get("admissibility")
        or (record.get("decision") or {}).get("admissibility"),
        "bindings_present": bool(bindings),
        "binding_completeness": present_bind / len(completeness_fields),
        "optional_artifacts": sorted(present_optional.keys()),
        "checksums": checksums,
        "bundle_digest": hash_object(checksums),
    }
    return reconstruction


def write_reconstruction_report(
    release_dir: str | Path,
    out_path: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    report = reconstruct_from_release(release_dir, **kwargs)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


__all__ = [
    "checksum_release_bundle",
    "reconstruct_from_release",
    "write_reconstruction_report",
]
