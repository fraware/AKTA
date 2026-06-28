"""Optional policy bundle signature verification (v0.4)."""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
from typing import Any

import yaml

from akta.errors import PolicyError
from akta.hash import hash_file_content


MANIFEST_FILENAME = "policy_manifest.yaml"
DEFAULT_HMAC_KEY = b"akta-dev-policy-integrity-v0.4-test-key"


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
    """Verify policy manifest when present or when AKTA_VERIFY_POLICY=1."""
    policy_dir = Path(policy_dir)
    if required is None:
        required = os.environ.get("AKTA_VERIFY_POLICY", "").lower() in ("1", "true", "yes")

    manifest = _load_manifest(policy_dir)
    if manifest is None:
        if required:
            raise PolicyError(f"Policy verification required but no {MANIFEST_FILENAME} found")
        return False

    verify_manifest_hashes(policy_dir, manifest)

    sig = manifest.get("signature")
    if sig:
        key_env = os.environ.get("AKTA_POLICY_HMAC_KEY")
        key = key_env.encode("utf-8") if key_env else DEFAULT_HMAC_KEY
        verify_hmac_signature(manifest, key)
    elif required:
        raise PolicyError("Policy manifest missing signature block")

    return True
