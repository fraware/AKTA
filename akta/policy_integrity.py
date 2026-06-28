"""Optional policy bundle signature verification (v0.6 Ed25519 + HMAC)."""

from __future__ import annotations

import base64
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
ED25519_ALGORITHM = "Ed25519"
HMAC_ALGORITHM = "HMAC-SHA256"


def is_production_mode() -> bool:
    """True when strict production policy verification is required."""
    prod = os.environ.get("AKTA_PRODUCTION_MODE", "").lower() in ("1", "true", "yes")
    verify = os.environ.get("AKTA_VERIFY_POLICY", "").lower() in ("1", "true", "yes")
    return prod or verify


def require_signed_policy() -> bool:
    """True when unsigned policy manifests must be rejected."""
    if os.environ.get("AKTA_REQUIRE_SIGNED_POLICY", "").lower() in ("1", "true", "yes"):
        return True
    return is_production_mode()


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


def _manifest_signing_payload(manifest: dict[str, Any]) -> bytes:
    return "|".join(
        f"{k}:{v}" for k, v in sorted(manifest.get("files", {}).items())
    ).encode("utf-8")


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

    if production and not os.environ.get("AKTA_POLICY_PUBLIC_KEY"):
        raise PolicyError(
            "Production mode requires AKTA_POLICY_HMAC_KEY or AKTA_POLICY_PUBLIC_KEY"
        )

    if production:
        return None

    return DEFAULT_HMAC_KEY


def verify_hmac_signature(manifest: dict[str, Any], key: bytes) -> None:
    """Verify HMAC-SHA256 signature over manifest file hashes."""
    sig_block = manifest.get("signature", {})
    if sig_block.get("algorithm") != HMAC_ALGORITHM:
        raise PolicyError(f"Unsupported signature algorithm: {sig_block.get('algorithm')}")
    expected = sig_block.get("value", "")
    computed = hmac.new(key, _manifest_signing_payload(manifest), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, expected):
        raise PolicyError("Policy manifest HMAC signature verification failed")


def _decode_public_key(raw: str) -> bytes:
    """Decode Ed25519 public key from hex or base64."""
    cleaned = raw.strip()
    if cleaned.startswith("ssh-ed25519"):
        raise PolicyError("OpenSSH public key format not supported; use hex or base64 raw key")
    try:
        if len(cleaned) == 64 and all(c in "0123456789abcdefABCDEF" for c in cleaned):
            return bytes.fromhex(cleaned)
        return base64.b64decode(cleaned)
    except ValueError as exc:
        raise PolicyError(f"Invalid Ed25519 public key encoding: {exc}") from exc


def _collect_verification_keys(manifest: dict[str, Any]) -> list[bytes]:
    """Collect public keys from env and manifest (supports key rotation)."""
    keys: list[bytes] = []
    env_key = os.environ.get("AKTA_POLICY_PUBLIC_KEY")
    if env_key:
        keys.append(_decode_public_key(env_key))

    for entry in manifest.get("public_keys") or []:
        if isinstance(entry, str):
            keys.append(_decode_public_key(entry))
        elif isinstance(entry, dict) and entry.get("public_key"):
            keys.append(_decode_public_key(str(entry["public_key"])))

    sig = manifest.get("signature") or {}
    if sig.get("public_key"):
        keys.append(_decode_public_key(str(sig["public_key"])))

    return keys


def verify_ed25519_signature(manifest: dict[str, Any]) -> None:
    """Verify Ed25519 signature over manifest file hashes."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise PolicyError(
            "Ed25519 verification requires cryptography package; "
            "pip install akta-protocol[security]"
        ) from exc

    sig_block = manifest.get("signature", {})
    if sig_block.get("algorithm") != ED25519_ALGORITHM:
        raise PolicyError(f"Unsupported signature algorithm: {sig_block.get('algorithm')}")

    signature_b64 = sig_block.get("value", "")
    if not signature_b64:
        raise PolicyError("Ed25519 signature block missing value")

    try:
        signature = base64.b64decode(signature_b64)
    except ValueError as exc:
        raise PolicyError(f"Invalid Ed25519 signature encoding: {exc}") from exc

    keys = _collect_verification_keys(manifest)
    if not keys:
        raise PolicyError(
            "Ed25519 verification requires AKTA_POLICY_PUBLIC_KEY or manifest public_keys"
        )

    payload = _manifest_signing_payload(manifest)
    last_error: Exception | None = None
    for key_bytes in keys:
        try:
            public_key = Ed25519PublicKey.from_public_bytes(key_bytes)
            public_key.verify(signature, payload)
            return
        except InvalidSignature as exc:
            last_error = exc
            continue
        except ValueError as exc:
            last_error = exc
            continue

    raise PolicyError("Policy manifest Ed25519 signature verification failed") from last_error


def sign_manifest_ed25519(manifest: dict[str, Any], private_key_bytes: bytes) -> dict[str, Any]:
    """Sign manifest with Ed25519 private key (32-byte seed or 64-byte expanded)."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as exc:
        raise PolicyError(
            "Ed25519 signing requires cryptography package; pip install akta-protocol[security]"
        ) from exc

    if len(private_key_bytes) == 32:
        private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    elif len(private_key_bytes) == 64:
        private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes[:32])
    else:
        raise PolicyError("Ed25519 private key must be 32 or 64 bytes")

    signature = private_key.sign(_manifest_signing_payload(manifest))
    public_bytes = private_key.public_key().public_bytes_raw()
    manifest = dict(manifest)
    manifest["signature"] = {
        "algorithm": ED25519_ALGORITHM,
        "value": base64.b64encode(signature).decode("ascii"),
        "public_key": base64.b64encode(public_bytes).decode("ascii"),
        "key_id": manifest.get("signature", {}).get("key_id") or "primary",
    }
    return manifest


def verify_policy_integrity(policy_dir: str | Path, *, required: bool | None = None) -> bool:
    """Verify policy manifest when present or when production/verify mode is active."""
    policy_dir = Path(policy_dir)
    production = is_production_mode()
    signed_required = require_signed_policy()
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
        algorithm = sig.get("algorithm", HMAC_ALGORITHM)
        if algorithm == ED25519_ALGORITHM:
            verify_ed25519_signature(manifest)
        elif algorithm == HMAC_ALGORITHM:
            key = _resolve_hmac_key(production=production)
            if key is None:
                raise PolicyError("Policy manifest HMAC signature present but no verification key configured")
            verify_hmac_signature(manifest, key)
            if not production and key == DEFAULT_HMAC_KEY:
                logger.warning(
                    "Policy HMAC verified with dev key; set AKTA_POLICY_HMAC_KEY for production"
                )
        else:
            raise PolicyError(f"Unsupported signature algorithm: {algorithm}")
    elif signed_required or production:
        raise PolicyError("Policy manifest missing signature block")

    return True
