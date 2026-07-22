"""Effective policy manifest generation and binding (directive §5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from akta.hash import hash_file_content, hash_object
from akta.policy_integrity import (
    MANIFEST_FILENAME,
    compute_file_hash,
    _load_manifest,
)

EFFECTIVE_MANIFEST_FILENAME = "effective_policy_manifest.json"

# Inputs required for a complete effective policy (include when present on disk).
EFFECTIVE_POLICY_INPUTS: tuple[str, ...] = (
    "action_ontology.yaml",
    "responsibility_levels.yaml",
    "evidence_states.yaml",
    "validation_statuses.yaml",
    "verification_statuses.yaml",
    "deployment_profiles.yaml",
    "admissibility_matrix.yaml",
    "evidence_to_action_matrix.yaml",
    "evidence_to_action_rules.yaml",
    "default_tool_registry.yaml",
    "tool_to_requested_scope.yaml",
    "structured_action_schema.yaml",
    "scope_grant_override_rules.yaml",
    "scope_compatibility_manifest.json",
    "release_keys.yaml",
    "policy_manifest.yaml",
)

OVERLAY_REGISTRY_NOTE = (
    "Domain overlays live under overlays/; registry metadata is recorded as "
    "overlay_ids + content hashes when overlays_dir is provided."
)


def _file_version(path: Path, data: Any) -> str:
    if isinstance(data, dict):
        return str(
            data.get("policy_file_version")
            or data.get("version")
            or data.get("policy_bundle_version")
            or "unknown"
        )
    return "unknown"


def collect_overlay_registry(overlays_dir: Path | None) -> dict[str, Any]:
    if overlays_dir is None or not overlays_dir.is_dir():
        return {"note": OVERLAY_REGISTRY_NOTE, "overlays": {}}
    overlays: dict[str, str] = {}
    for path in sorted(overlays_dir.glob("*.yaml")):
        overlays[path.name] = compute_file_hash(path)
    return {"note": OVERLAY_REGISTRY_NOTE, "overlays": overlays}


def build_effective_policy_manifest(
    policy_dir: str | Path,
    *,
    overlays_dir: str | Path | None = None,
    integrity_mode: str = "dev_unsigned",
) -> dict[str, Any]:
    """Build effective_policy_manifest covering available policy inputs."""
    policy_dir = Path(policy_dir)
    files: dict[str, str] = {}
    file_versions: dict[str, str] = {}
    missing: list[str] = []

    for name in EFFECTIVE_POLICY_INPUTS:
        path = policy_dir / name
        if not path.is_file():
            missing.append(name)
            continue
        text = path.read_text(encoding="utf-8")
        files[name] = hash_file_content(text)
        if name.endswith(".yaml"):
            parsed = yaml.safe_load(text) or {}
            file_versions[name] = _file_version(path, parsed)
        elif name.endswith(".json"):
            parsed = json.loads(text)
            file_versions[name] = _file_version(path, parsed)
        else:
            file_versions[name] = "unknown"

    base_manifest = _load_manifest(policy_dir) or {}
    bundle_version = (
        base_manifest.get("bundle_version")
        or base_manifest.get("version")
        or "akta-core-v1.0"
    )
    sig = base_manifest.get("signature") or {}
    signing_key_id = sig.get("key_id")

    overlay_registry = collect_overlay_registry(
        Path(overlays_dir) if overlays_dir else policy_dir.parent / "overlays"
    )

    effective_policy_hash = hash_object({
        "files": files,
        "file_versions": file_versions,
        "overlay_registry": overlay_registry,
        "bundle_version": bundle_version,
    })
    # Canonical JSON for manifest_hash excludes the hash fields themselves.
    body_for_hash = {
        "manifest_version": "akta-effective-policy-v1.0",
        "bundle_version": bundle_version,
        "integrity_mode": integrity_mode,
        "signing_key_id": signing_key_id,
        "files": files,
        "file_versions": file_versions,
        "overlay_registry": overlay_registry,
        "missing_optional_inputs": missing,
        "policy_manifest_signature": {
            "algorithm": sig.get("algorithm"),
            "key_id": signing_key_id,
            "present": bool(sig),
        },
    }
    manifest_hash = hash_object(body_for_hash)

    return {
        **body_for_hash,
        "effective_policy_hash": effective_policy_hash,
        "manifest_hash": manifest_hash,
        "policy_manifest_signature": {
            "algorithm": sig.get("algorithm"),
            "key_id": signing_key_id,
            "value": sig.get("value"),
            "present": bool(sig),
        },
    }


def write_effective_policy_manifest(
    policy_dir: str | Path,
    *,
    overlays_dir: str | Path | None = None,
    integrity_mode: str = "dev_unsigned",
) -> Path:
    """Write effective_policy_manifest.json under policy_dir."""
    policy_dir = Path(policy_dir)
    manifest = build_effective_policy_manifest(
        policy_dir,
        overlays_dir=overlays_dir,
        integrity_mode=integrity_mode,
    )
    out = policy_dir / EFFECTIVE_MANIFEST_FILENAME
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def load_effective_policy_manifest(policy_dir: str | Path) -> dict[str, Any] | None:
    path = Path(policy_dir) / EFFECTIVE_MANIFEST_FILENAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def policy_binding_block(
    *,
    bundle_version: str,
    effective_policy_hash: str,
    manifest_hash: str,
    integrity_mode: str,
    signing_key_id: str | None,
    file_versions: dict[str, str],
) -> dict[str, Any]:
    """Canonical policy provenance block for Decision and Record artifacts."""
    return {
        "bundle_version": bundle_version,
        "effective_policy_hash": effective_policy_hash,
        "manifest_hash": manifest_hash,
        "integrity_mode": integrity_mode,
        "signing_key_id": signing_key_id,
        "file_versions": dict(file_versions),
    }
