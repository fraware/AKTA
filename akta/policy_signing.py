"""Policy integrity modes and verification orchestration (v0.7)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from akta.errors import PolicyError
from akta.policy_integrity import (
    ED25519_ALGORITHM,
    HMAC_ALGORITHM,
    MANIFEST_FILENAME,
    _collect_verification_keys,
    _load_manifest,
    _resolve_hmac_key,
    compute_file_hash,
    is_production_mode,
    require_signed_policy,
    verify_ed25519_signature,
    verify_hmac_signature,
    verify_manifest_hashes,
)

logger = logging.getLogger(__name__)

INTEGRITY_MODE_DEV_UNSIGNED = "dev_unsigned"
INTEGRITY_MODE_DEPLOYMENT_HMAC_ATTESTED = "deployment_hmac_attested"
INTEGRITY_MODE_RELEASE_ED25519_SIGNED = "release_ed25519_signed"

VALID_INTEGRITY_MODES = frozenset({
    INTEGRITY_MODE_DEV_UNSIGNED,
    INTEGRITY_MODE_DEPLOYMENT_HMAC_ATTESTED,
    INTEGRITY_MODE_RELEASE_ED25519_SIGNED,
})

RELEASE_KEYS_FILENAME = "release_keys.yaml"


@dataclass(frozen=True)
class PolicyIntegrityResult:
  verified: bool
  integrity_mode: str
  manifest_present: bool


def _release_keys_path(policy_dir: Path) -> Path:
    return policy_dir / RELEASE_KEYS_FILENAME


def load_release_key_registry(policy_dir: Path) -> dict[str, Any]:
    path = _release_keys_path(policy_dir)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _registry_public_keys(registry: dict[str, Any]) -> list[dict[str, Any]]:
    keys = registry.get("keys") or []
    return [k for k in keys if isinstance(k, dict)]


def verify_ed25519_against_release_registry(
    manifest: dict[str, Any],
    policy_dir: Path,
) -> bool:
    """Return True when Ed25519 signature matches an active release registry key."""
    registry = load_release_key_registry(policy_dir)
    registry_keys = _registry_public_keys(registry)
    if not registry_keys:
        return False

    sig_block = manifest.get("signature") or {}
    if sig_block.get("algorithm") != ED25519_ALGORITHM:
        return False

    key_id = sig_block.get("key_id")
    for entry in registry_keys:
        if entry.get("status") not in (None, "active"):
            continue
        if key_id and entry.get("key_id") != key_id:
            continue
        augmented = dict(manifest)
        augmented.setdefault("public_keys", [])
        if entry.get("public_key"):
            augmented["public_keys"] = list(augmented["public_keys"]) + [entry]
        try:
            verify_ed25519_signature(augmented)
            return True
        except PolicyError:
            continue
    return False


def detect_integrity_mode(
    policy_dir: Path,
    manifest: dict[str, Any] | None,
    *,
    production: bool,
    signed_required: bool,
) -> str:
    """Classify policy bundle integrity mode from manifest and environment."""
    if manifest is None:
        if production or signed_required:
            raise PolicyError(f"Policy verification required but no {MANIFEST_FILENAME} found")
        return INTEGRITY_MODE_DEV_UNSIGNED

    sig = manifest.get("signature")
    if not sig:
        if production or signed_required:
            raise PolicyError("Policy manifest missing signature block")
        return INTEGRITY_MODE_DEV_UNSIGNED

    algorithm = sig.get("algorithm", HMAC_ALGORITHM)
    if algorithm == ED25519_ALGORITHM:
        if verify_ed25519_against_release_registry(manifest, policy_dir):
            return INTEGRITY_MODE_RELEASE_ED25519_SIGNED
        if signed_required:
            raise PolicyError(
                "Ed25519 signature does not match active keys in policy/release_keys.yaml"
            )
        verify_ed25519_signature(manifest)
        return INTEGRITY_MODE_RELEASE_ED25519_SIGNED

    if algorithm == HMAC_ALGORITHM:
        if signed_required:
            raise PolicyError(
                "AKTA_REQUIRE_SIGNED_POLICY requires release_ed25519_signed manifest; "
                "HMAC-only policy is deployment attestation, not public release authenticity"
            )
        return INTEGRITY_MODE_DEPLOYMENT_HMAC_ATTESTED

    raise PolicyError(f"Unsupported signature algorithm: {algorithm}")


def verify_policy_bundle_integrity(
    policy_dir: str | Path,
    *,
    required: bool | None = None,
) -> PolicyIntegrityResult:
    """Verify policy manifest and return integrity mode (v0.7)."""
    policy_dir = Path(policy_dir)
    production = is_production_mode()
    signed_required = require_signed_policy()
    if required is None:
        required = production

    manifest = _load_manifest(policy_dir)
    manifest_present = manifest is not None

    if manifest is None:
        if required or production:
            raise PolicyError(f"Policy verification required but no {MANIFEST_FILENAME} found")
        return PolicyIntegrityResult(
            verified=False,
            integrity_mode=INTEGRITY_MODE_DEV_UNSIGNED,
            manifest_present=False,
        )

    verify_manifest_hashes(policy_dir, manifest)

    integrity_mode = detect_integrity_mode(
        policy_dir,
        manifest,
        production=production,
        signed_required=signed_required,
    )

    sig = manifest.get("signature") or {}
    algorithm = sig.get("algorithm", HMAC_ALGORITHM)

    if algorithm == ED25519_ALGORITHM:
        if integrity_mode == INTEGRITY_MODE_RELEASE_ED25519_SIGNED:
            if not verify_ed25519_against_release_registry(manifest, policy_dir):
                verify_ed25519_signature(manifest)
        else:
            verify_ed25519_signature(manifest)
    elif algorithm == HMAC_ALGORITHM:
        key = _resolve_hmac_key(production=production)
        if key is None:
            raise PolicyError("Policy manifest HMAC signature present but no verification key configured")
        verify_hmac_signature(manifest, key)
        if not production and key == b"akta-dev-policy-integrity-v0.4-test-key":
            logger.warning(
                "Policy HMAC verified with dev key; set AKTA_POLICY_HMAC_KEY for production"
            )
    else:
        raise PolicyError(f"Unsupported signature algorithm: {algorithm}")

    return PolicyIntegrityResult(
        verified=True,
        integrity_mode=integrity_mode,
        manifest_present=True,
    )


def attach_integrity_provenance(provenance: dict[str, Any], integrity_mode: str) -> dict[str, Any]:
    """Add integrity_mode to provenance block (exact vocabulary)."""
    if integrity_mode not in VALID_INTEGRITY_MODES:
        raise ValueError(f"Invalid integrity_mode: {integrity_mode}")
    updated = dict(provenance)
    updated["integrity_mode"] = integrity_mode
    return updated
