"""Effective policy manifest generation and binding (directive §5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from akta.hash import hash_file_content, hash_object
from akta.policy_integrity import (
    _load_manifest,
    compute_file_hash,
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


def verify_effective_policy_manifest(
    policy_dir: str | Path,
    *,
    overlays_dir: str | Path | None = None,
    integrity_mode: str = "dev_unsigned",
    stored: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rebuild effective policy from current files and compare to stored (P0-G).

    Does NOT trust hashes copied from effective_policy_manifest.json without
    recomputation. Rejects stale/tampered inputs.
    """
    policy_dir = Path(policy_dir)
    recomputed = build_effective_policy_manifest(
        policy_dir,
        overlays_dir=overlays_dir,
        integrity_mode=integrity_mode,
    )
    stored_manifest = stored if stored is not None else load_effective_policy_manifest(policy_dir)
    errors: list[str] = []
    if stored_manifest is None:
        return {
            "ok": True,
            "recomputed": recomputed,
            "stored": None,
            "errors": [],
            "note": "no stored effective_policy_manifest; recomputed accepted",
        }

    for key in ("effective_policy_hash", "manifest_hash", "bundle_version"):
        if stored_manifest.get(key) != recomputed.get(key):
            errors.append(
                f"effective policy {key} mismatch: stored={stored_manifest.get(key)!r} "
                f"recomputed={recomputed.get(key)!r}"
            )

    stored_files = stored_manifest.get("files") or {}
    recomputed_files = recomputed.get("files") or {}
    all_names = sorted(set(stored_files) | set(recomputed_files))
    for name in all_names:
        if stored_files.get(name) != recomputed_files.get(name):
            errors.append(
                f"policy file hash drift for {name}: "
                f"stored={stored_files.get(name)!r} recomputed={recomputed_files.get(name)!r}"
            )

    stored_overlays = (stored_manifest.get("overlay_registry") or {}).get("overlays") or {}
    recomputed_overlays = (recomputed.get("overlay_registry") or {}).get("overlays") or {}
    for name in sorted(set(stored_overlays) | set(recomputed_overlays)):
        if stored_overlays.get(name) != recomputed_overlays.get(name):
            errors.append(f"overlay registry hash drift for {name}")

    # Mutating critical inputs after manifest generation must fail.
    critical = {
        "default_tool_registry.yaml",
        "tool_to_requested_scope.yaml",
        "scope_grant_override_rules.yaml",
        "structured_action_schema.yaml",
        "scope_compatibility_manifest.json",
        "release_keys.yaml",
    }
    for name in critical:
        if name in stored_files and name in recomputed_files:
            if stored_files[name] != recomputed_files[name]:
                errors.append(
                    f"mutating {name} after effective manifest generation is rejected"
                )

    return {
        "ok": not errors,
        "recomputed": recomputed,
        "stored": stored_manifest,
        "errors": errors,
    }


def require_effective_policy_integrity(
    policy_dir: str | Path,
    *,
    overlays_dir: str | Path | None = None,
    integrity_mode: str = "dev_unsigned",
) -> dict[str, Any]:
    """Raise PolicyError when stored effective policy does not match recomputation."""
    from akta.errors import PolicyError

    result = verify_effective_policy_manifest(
        policy_dir,
        overlays_dir=overlays_dir,
        integrity_mode=integrity_mode,
    )
    if not result["ok"]:
        raise PolicyError(
            "effective policy provenance failed: " + "; ".join(result["errors"])
        )
    return result["recomputed"]


def policy_binding_block(
    *,
    bundle_version: str,
    effective_policy_hash: str,
    manifest_hash: str,
    integrity_mode: str,
    signing_key_id: str | None,
    file_versions: dict[str, str],
    schema_hashes: dict[str, str] | None = None,
    overlay_hash: str | None = None,
    release_key_id: str | None = None,
) -> dict[str, Any]:
    """Canonical policy provenance block for Decision and Record artifacts."""
    block: dict[str, Any] = {
        "bundle_version": bundle_version,
        "effective_policy_hash": effective_policy_hash,
        "manifest_hash": manifest_hash,
        "integrity_mode": integrity_mode,
        "signing_key_id": signing_key_id,
        "release_key_id": release_key_id or signing_key_id,
        "file_versions": dict(file_versions),
    }
    if schema_hashes:
        block["schema_hashes"] = dict(schema_hashes)
    if overlay_hash:
        block["overlay_hash"] = overlay_hash
    return block
