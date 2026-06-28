"""Optional policy bundle signature verification (v0.5)."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from akta.errors import PolicyError
from akta.hash import hash_file_content

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "policy_manifest.yaml"
DEFAULT_HMAC_KEY = b"akta-dev-policy-integrity-v0.4-test-key"
DEV_HMAC_KEY_LABEL = "akta-dev-policy-integrity"


def is_production_mode() -> bool:
    """True when strict production policy verification is required."""
    prod = os.environ.get("AKTA_PRODUCTION_MODE", "").lower() in ("1", "true", "yes")
    verify = os.environ.get("AKTA_VERIFY_POLICY", "").lower() in ("1", "true", "yes")
    return prod or verify


def _load_manifest(policy_dir: Path) -> dict[str, Any] | None:
    path = policy_dir / MANIFEST_FILENAME
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def compute_file_hash(path: Path) -> str:
    return hash_file_content(path.read_text(encoding="utf-8"))


def verify_manifest_hashes(policy_dir: Path, manifest: dict[str, Any]) -> None:
    """Verify listed file hashes match on-disk content."""
    files = manifest.get("files", {})
    for rel_path, expected_hash in files.items():
        file_path = policy_dir / rel_path
        if not file_path.exists():
            raise PolicyError(f"Policy manifest lists missing file: {rel_path}")
        actual = compute_file_hash(file_path)
        if actual != expected_hash:
            raise PolicyError(
                f"Policy integrity hash mismatch for {rel_path}: "
                f"expected {expected_hash}, got {actual}"
            )


def _resolve_hmac_key(*, production: bool) -> bytes | None:
    """Resolve HMAC key; reject dev key in production."""
    key_env = os.environ.get("AKTA_POLICY_HMAC_KEY")
    if key_env:
        if production and DEV_HMAC_KEY_LABEL in key_env:
            raise PolicyError(
                "Production mode rejects in-repo dev HMAC key; "
                "set AKTA_POLICY_HMAC_KEY to a deployment-specific secret"
            )
        return key_env.encode("utf-8")

    pub_key = os.environ.get("AKTA_POLICY_PUBLIC_KEY")
    if pub_key and production:
        raise PolicyError(
            "Ed25519 public-key verification not yet implemented; "
            "use AKTA_POLICY_HMAC_KEY in production"
        )

    if production:
        raise PolicyError(
            "Production mode requires AKTA_POLICY_HMAC_KEY or AKTA_POLICY_PUBLIC_KEY"
        )

    return DEFAULT_HMAC_KEY


def verify_hmac_signature(manifest: dict[str, Any], key: bytes) -> None:
    """Verify HMAC-SHA256 signature over manifest file hashes."""
    sig_block = manifest.get("signature", {})
    if sig_block.get("algorithm") != "HMAC-SHA256":
        raise PolicyError(f"Unsupported signature algorithm: {sig_block.get('algorithm')}")
    expected = sig_block.get("value", "")
    payload = "|".join(
        f"{k}:{v}" for k, v in sorted(manifest.get("files", {}).items())
    )
    computed = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, expected):
        raise PolicyError("Policy manifest HMAC signature verification failed")


def verify_policy_integrity(policy_dir: str | Path, *, required: bool | None = None) -> bool:
    """Verify policy manifest when present or when production/verify mode is active."""
    policy_dir = Path(policy_dir)
    production = is_production_mode()
    if required is None:
        required = production

    manifest = _load_manifest(policy_dir)
    if manifest is None:
        if required or production:
            raise PolicyError(f"Policy verification required but no {MANIFEST_FILENAME} found")
        return False

    verify_manifest_hashes(policy_dir, manifest)

    sig = manifest.get("signature")
    if sig:
        key = _resolve_hmac_key(production=production)
        if key is None:
            raise PolicyError("Policy manifest signature present but no verification key configured")
        verify_hmac_signature(manifest, key)
        if not production and key == DEFAULT_HMAC_KEY:
            logger.warning(
                "Policy HMAC verified with dev key; set AKTA_POLICY_HMAC_KEY for production"
            )
    elif production:
        raise PolicyError("Policy manifest missing signature block")

    return True
