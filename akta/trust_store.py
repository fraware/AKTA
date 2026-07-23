"""SCOPE issuer / trust-root key registry for grant authentication (P0-C).

Loads approved issuer public keys from AKTA policy and optional SCOPE sibling
``reviewer_key_registry.yaml`` / issuer registry files. Production and other
strict modes fail closed when keys are unknown, revoked, or the store is empty.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from akta.shared_contracts import _contracts

_AKTA_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY_NAME = "scope_issuer_key_registry.yaml"
SUPPORTED_ALGORITHMS = frozenset({"Ed25519", "ed25519"})
ACTIVE_STATUSES = frozenset({"active"})


def _public_key_ref_from_pem(pem: str | bytes) -> str:
    text = pem.decode("ascii") if isinstance(pem, bytes) else pem
    return _contracts().compute_hash({"public_key_pem": text})


def _load_ed25519_public_key(entry: dict[str, Any], *, base_dir: Path):
    """Return cryptography Ed25519PublicKey from registry entry."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    pem_text = entry.get("public_key_pem")
    if pem_text:
        key = serialization.load_pem_public_key(
            pem_text.encode("ascii") if isinstance(pem_text, str) else pem_text
        )
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("issuer public key must be Ed25519")
        return key

    path_value = entry.get("public_key_file") or entry.get("public_key_path")
    if path_value:
        path = Path(str(path_value))
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        key = serialization.load_pem_public_key(path.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError(f"issuer public key must be Ed25519: {path}")
        return key

    raw = entry.get("public_key")
    if raw:
        cleaned = str(raw).strip()
        if len(cleaned) == 64 and all(c in "0123456789abcdefABCDEF" for c in cleaned):
            key_bytes = bytes.fromhex(cleaned)
        else:
            key_bytes = base64.b64decode(cleaned)
        return Ed25519PublicKey.from_public_bytes(key_bytes)

    raise ValueError("issuer entry missing public_key_pem, public_key_file, or public_key")


def _verify_ed25519_over_hash(
    public_key: Any,
    *,
    payload: dict[str, Any],
    hash_field: str,
    signature: str,
) -> bool:
    from cryptography.exceptions import InvalidSignature

    if hash_field not in payload:
        return False
    digest = str(payload[hash_field]).removeprefix("sha256:")
    try:
        public_key.verify(base64.b64decode(signature), bytes.fromhex(digest))
        return True
    except (InvalidSignature, ValueError):
        return False


def _entry_status(entry: dict[str, Any]) -> str:
    return str(entry.get("status") or "active").strip().lower()


def _parse_iso8601(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _entry_within_validity(entry: dict[str, Any], *, now: datetime | None = None) -> bool:
    """Return False when valid_from/valid_until exclude the current time."""
    clock = now or datetime.now(timezone.utc)
    start = _parse_iso8601(entry.get("valid_from"))
    end = _parse_iso8601(entry.get("valid_until"))
    if start is not None and clock < start:
        return False
    if end is not None and clock > end:
        return False
    return True


def _entry_algorithm_ok(entry: dict[str, Any]) -> bool:
    algo = entry.get("algorithm")
    if algo is None or algo == "":
        # Legacy SCOPE reviewer entries omit algorithm; treat as Ed25519.
        return True
    return str(algo) in SUPPORTED_ALGORITHMS


def _entry_usable(entry: dict[str, Any], *, now: datetime | None = None) -> bool:
    if _entry_status(entry) not in ACTIVE_STATUSES:
        return False
    if not _entry_algorithm_ok(entry):
        return False
    return _entry_within_validity(entry, now=now)


def load_issuer_registry(path: str | Path) -> dict[str, Any]:
    """Load an AKTA or SCOPE-shaped issuer/reviewer key registry YAML/JSON."""
    registry_path = Path(path)
    if not registry_path.is_file():
        return {"version": None, "keys": {}, "revoked_key_ids": [], "source": str(registry_path)}

    raw = registry_path.read_text(encoding="utf-8")
    if registry_path.suffix.lower() == ".json":
        data = json.loads(raw) or {}
    else:
        data = yaml.safe_load(raw) or {}

    keys: dict[str, dict[str, Any]] = {}
    revoked: set[str] = set(str(x) for x in (data.get("revoked_key_ids") or []))

    # AKTA issuer registry shape
    issuers = data.get("issuers") or {}
    for key_id, entry in issuers.items():
        if not isinstance(entry, dict):
            continue
        normalized = dict(entry)
        normalized.setdefault("key_id", str(key_id))
        if _entry_status(normalized) == "revoked":
            revoked.add(str(key_id))
            if normalized.get("public_key_ref"):
                revoked.add(str(normalized["public_key_ref"]))
        keys[str(key_id)] = normalized
        ref = normalized.get("public_key_ref")
        if ref:
            keys[str(ref)] = normalized

    # SCOPE reviewer_key_registry.yaml shape
    reviewers = data.get("reviewers") or {}
    for reviewer_id, entry in reviewers.items():
        if isinstance(entry, str):
            entry = {"public_key_ref": entry}
        if not isinstance(entry, dict):
            continue
        normalized = dict(entry)
        normalized.setdefault("key_id", str(reviewer_id))
        normalized.setdefault("issuer_identity", str(reviewer_id))
        if _entry_status(normalized) == "revoked":
            revoked.add(str(reviewer_id))
            if normalized.get("public_key_ref"):
                revoked.add(str(normalized["public_key_ref"]))
        keys[str(reviewer_id)] = normalized
        ref = normalized.get("public_key_ref")
        if ref:
            keys[str(ref)] = normalized

    return {
        "version": data.get("version"),
        "keys": keys,
        "revoked_key_ids": sorted(revoked),
        "source": str(registry_path.resolve()),
        "raw": data,
    }


def _default_registry_candidates(policy_dir: Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    env = os.environ.get("AKTA_TRUST_STORE_PATH", "").strip()
    if env:
        candidates.append(Path(env))
    env_reg = os.environ.get("AKTA_ISSUER_KEY_REGISTRY", "").strip()
    if env_reg:
        candidates.append(Path(env_reg))
    base = Path(policy_dir) if policy_dir else _AKTA_ROOT / "policy"
    candidates.append(base / DEFAULT_REGISTRY_NAME)

    scope_repo = os.environ.get("SCOPE_REPO_PATH", "").strip()
    scope_roots: list[Path] = []
    if scope_repo:
        scope_roots.append(Path(scope_repo))
    scope_roots.append(_AKTA_ROOT.parent / "SCOPE")
    for root in scope_roots:
        candidates.append(root / "policy" / "reviewer_key_registry.yaml")
        candidates.append(root / "policy" / "issuer_key_registry.yaml")
    return candidates


def merge_registries(parts: list[dict[str, Any]]) -> dict[str, Any]:
    keys: dict[str, dict[str, Any]] = {}
    revoked: set[str] = set()
    sources: list[str] = []
    for part in parts:
        sources.append(str(part.get("source") or ""))
        revoked.update(str(x) for x in (part.get("revoked_key_ids") or []))
        for key_id, entry in (part.get("keys") or {}).items():
            keys[str(key_id)] = dict(entry)
    return {
        "keys": keys,
        "revoked_key_ids": sorted(revoked),
        "sources": [s for s in sources if s],
    }


def build_trust_store(
    registry: dict[str, Any],
    *,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Build a verifier trust_store dict consumed by ``scope_grant_verifier``."""
    base = base_dir or _AKTA_ROOT / "policy"
    keys = dict(registry.get("keys") or {})
    revoked = set(str(x) for x in (registry.get("revoked_key_ids") or []))
    loaded_keys: dict[str, dict[str, Any]] = {}

    for key_id, entry in keys.items():
        enriched = dict(entry)
        try:
            public_key = _load_ed25519_public_key(enriched, base_dir=base)
            pem = None
            if enriched.get("public_key_pem"):
                pem = str(enriched["public_key_pem"])
            elif enriched.get("public_key_file") or enriched.get("public_key_path"):
                path_value = enriched.get("public_key_file") or enriched.get("public_key_path")
                path = Path(str(path_value))
                if not path.is_absolute():
                    path = (base / path).resolve()
                pem = path.read_text(encoding="ascii")
            if pem and not enriched.get("public_key_ref"):
                enriched["public_key_ref"] = _public_key_ref_from_pem(pem)
            enriched["_public_key"] = public_key
            loaded_keys[str(key_id)] = enriched
            ref = enriched.get("public_key_ref")
            if ref:
                loaded_keys[str(ref)] = enriched
        except Exception:
            # Keep structural entry for unknown-key messaging; crypto verify will fail.
            loaded_keys[str(key_id)] = enriched

    def _verify(payload: dict[str, Any], hash_field: str, signature: str) -> bool:
        issuer = payload.get("issuer") or {}
        key_id = (
            issuer.get("issuer_key_id")
            or payload.get("reviewer_public_key_ref")
            or payload.get("attestation_key_id")
            or payload.get("issuer_key_id")
        )
        if not key_id:
            return False
        if str(key_id) in revoked:
            return False
        entry = loaded_keys.get(str(key_id))
        if entry is None:
            return False
        if not _entry_usable(entry):
            return False
        public_key = entry.get("_public_key")
        if public_key is None:
            return False
        # SCOPE parity: signed_payload_hash must equal the hashed field when present.
        signed_payload = payload.get("signed_payload_hash")
        if signed_payload is not None and signed_payload != payload.get(hash_field):
            return False
        return _verify_ed25519_over_hash(
            public_key,
            payload=payload,
            hash_field=hash_field,
            signature=signature,
        )

    return {
        "keys": loaded_keys,
        "revoked_key_ids": sorted(revoked),
        "sources": list(registry.get("sources") or ([registry.get("source")] if registry.get("source") else [])),
        "verify": _verify,
    }


def resolve_trust_store(
    *,
    policy_dir: str | Path | None = None,
    explicit: dict[str, Any] | None = None,
    require_keys: bool = False,
) -> dict[str, Any] | None:
    """Resolve production trust store from explicit override or on-disk registries."""
    if explicit is not None:
        if "verify" not in explicit and explicit.get("keys") is not None:
            return build_trust_store(explicit, base_dir=Path(policy_dir) if policy_dir else None)
        return explicit

    built_parts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in _default_registry_candidates(Path(policy_dir) if policy_dir else None):
        resolved = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            part = load_issuer_registry(candidate)
            built_parts.append(build_trust_store(part, base_dir=candidate.parent))

    if not built_parts:
        if require_keys:
            return build_trust_store({"keys": {}, "revoked_key_ids": []})
        return None

    # Merge already-built stores so relative public_key_file paths resolve per registry.
    keys: dict[str, dict[str, Any]] = {}
    revoked: set[str] = set()
    sources: list[str] = []
    for part in built_parts:
        sources.extend(str(s) for s in (part.get("sources") or []) if s)
        revoked.update(str(x) for x in (part.get("revoked_key_ids") or []))
        for key_id, entry in (part.get("keys") or {}).items():
            keys[str(key_id)] = dict(entry)

    def _verify(payload: dict[str, Any], hash_field: str, signature: str) -> bool:
        issuer = payload.get("issuer") or {}
        key_id = (
            issuer.get("issuer_key_id")
            or payload.get("reviewer_public_key_ref")
            or payload.get("attestation_key_id")
            or payload.get("issuer_key_id")
        )
        if not key_id or str(key_id) in revoked:
            return False
        entry = keys.get(str(key_id))
        if entry is None or not _entry_usable(entry):
            return False
        public_key = entry.get("_public_key")
        if public_key is None:
            return False
        signed_payload = payload.get("signed_payload_hash")
        if signed_payload is not None and signed_payload != payload.get(hash_field):
            return False
        return _verify_ed25519_over_hash(
            public_key,
            payload=payload,
            hash_field=hash_field,
            signature=signature,
        )

    store = {
        "keys": keys,
        "revoked_key_ids": sorted(revoked),
        "sources": sources,
        "verify": _verify,
    }
    if require_keys and institutional_registry_is_empty(store):
        return store
    return store


def sign_payload_hash_ed25519(private_key_pem: bytes, digest_field_value: str) -> str:
    """Test helper: SCOPE-compatible Ed25519 signature over sha256 digest bytes."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("private key must be Ed25519")
    digest = digest_field_value.removeprefix("sha256:")
    return base64.b64encode(key.sign(bytes.fromhex(digest))).decode("ascii")


def generate_test_keypair(directory: str | Path) -> dict[str, str]:
    """Generate an Ed25519 keypair for unit tests; returns paths and public_key_ref."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    priv_path = directory / "issuer_ed25519.pem"
    pub_path = directory / "issuer_ed25519.pub.pem"
    priv_path.write_bytes(private_pem)
    pub_path.write_bytes(public_pem)
    return {
        "private_key_path": str(priv_path),
        "public_key_path": str(pub_path),
        "public_key_pem": public_pem.decode("ascii"),
        "public_key_ref": _public_key_ref_from_pem(public_pem),
    }


def institutional_registry_is_empty(store: dict[str, Any] | None) -> bool:
    """True when no usable active keys are present (production fail-closed)."""
    if store is None:
        return True
    keys = store.get("keys") or {}
    revoked = set(str(x) for x in (store.get("revoked_key_ids") or []))
    for key_id, entry in keys.items():
        if str(key_id) in revoked:
            continue
        if isinstance(entry, dict) and _entry_usable(entry) and entry.get("_public_key") is not None:
            return False
    return True


__all__ = [
    "SUPPORTED_ALGORITHMS",
    "build_trust_store",
    "generate_test_keypair",
    "institutional_registry_is_empty",
    "load_issuer_registry",
    "merge_registries",
    "resolve_trust_store",
    "sign_payload_hash_ed25519",
]
