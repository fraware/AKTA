"""SCOPE trust registries for grant, status, and manifest authentication (AKTA 1.1).

Trust domains are separate:
- ``scope_grant_issuer_registry.yaml`` — grant signatures only
- ``scope_status_attestation_registry.yaml`` — grant-status attestations
- ``scope_policy_manifest_signer_registry.yaml`` — SCOPE authorization manifests
- ``reviewer_decision_registry.yaml`` — optional local reviewer decisions;
  **never** auto-merged into grant-issuer keys
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from akta.shared_contracts import _contracts

_AKTA_ROOT = Path(__file__).resolve().parent.parent

GRANT_ISSUER_REGISTRY_NAME = "scope_grant_issuer_registry.yaml"
STATUS_ATTESTATION_REGISTRY_NAME = "scope_status_attestation_registry.yaml"
MANIFEST_SIGNER_REGISTRY_NAME = "scope_policy_manifest_signer_registry.yaml"
REVIEWER_DECISION_REGISTRY_NAME = "reviewer_decision_registry.yaml"
# Legacy filename retained for migration messaging only — not auto-loaded as issuer.
LEGACY_ISSUER_REGISTRY_NAME = "scope_issuer_key_registry.yaml"

SUPPORTED_ALGORITHMS = frozenset({"Ed25519", "ed25519"})
ACTIVE_STATUSES = frozenset({"active"})


class ArtifactType(str, Enum):
    SCOPE_GRANT = "scope_grant"
    SCOPE_GRANT_STATUS = "scope_grant_status"
    SCOPE_AUTHORIZATION_MANIFEST = "scope_authorization_manifest"
    REVIEWER_DECISION = "reviewer_decision"


DEFAULT_ARTIFACT_TYPES: dict[str, frozenset[str]] = {
    GRANT_ISSUER_REGISTRY_NAME: frozenset({ArtifactType.SCOPE_GRANT.value}),
    STATUS_ATTESTATION_REGISTRY_NAME: frozenset({ArtifactType.SCOPE_GRANT_STATUS.value}),
    MANIFEST_SIGNER_REGISTRY_NAME: frozenset(
        {ArtifactType.SCOPE_AUTHORIZATION_MANIFEST.value}
    ),
    REVIEWER_DECISION_REGISTRY_NAME: frozenset({ArtifactType.REVIEWER_DECISION.value}),
}


def _public_key_ref_from_pem(pem: str | bytes) -> str:
    text = pem.decode("ascii") if isinstance(pem, bytes) else pem
    return _contracts().compute_hash({"public_key_pem": text})


def _require_cryptography():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:  # pragma: no cover - cryptography is a hard dep
        raise ImportError(
            "cryptography is required for SCOPE grant signature verification"
        ) from exc
    return serialization, Ed25519PublicKey


def _load_ed25519_public_key(entry: dict[str, Any], *, base_dir: Path):
    """Return cryptography Ed25519PublicKey from registry entry."""
    serialization, Ed25519PublicKey = _require_cryptography()

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


def entry_within_validity(entry: dict[str, Any], *, now: datetime | None = None) -> bool:
    """Return False when valid_from/valid_until exclude the current time."""
    clock = now or datetime.now(timezone.utc)
    start = _parse_iso8601(entry.get("valid_from"))
    end = _parse_iso8601(entry.get("valid_until"))
    if start is not None and clock < start:
        return False
    if end is not None and clock > end:
        return False
    return True


def _entry_within_validity(entry: dict[str, Any], *, now: datetime | None = None) -> bool:
    return entry_within_validity(entry, now=now)


def _entry_algorithm_ok(entry: dict[str, Any]) -> bool:
    algo = entry.get("algorithm")
    if algo is None or algo == "":
        return True
    return str(algo) in SUPPORTED_ALGORITHMS


def _normalize_artifact_types(
    entry: dict[str, Any],
    *,
    default_types: frozenset[str] | None = None,
) -> frozenset[str]:
    raw = entry.get("authorized_artifact_types") or entry.get("artifact_types")
    if raw is None:
        return frozenset(default_types or ())
    if isinstance(raw, str):
        return frozenset({raw.strip()}) if raw.strip() else frozenset()
    return frozenset(str(x).strip() for x in raw if str(x).strip())


def _entry_usable(
    entry: dict[str, Any],
    *,
    now: datetime | None = None,
    required_artifact_type: str | None = None,
) -> bool:
    if _entry_status(entry) not in ACTIVE_STATUSES:
        return False
    if not _entry_algorithm_ok(entry):
        return False
    if not _entry_within_validity(entry, now=now):
        return False
    if required_artifact_type is not None:
        allowed = entry.get("_authorized_artifact_types")
        if allowed is None:
            allowed = _normalize_artifact_types(entry)
        if required_artifact_type not in allowed:
            return False
    return True


def _normalize_registry_entry(
    key_id: str,
    entry: dict[str, Any],
    *,
    default_artifact_types: frozenset[str] | None = None,
) -> dict[str, Any]:
    normalized = dict(entry)
    normalized.setdefault("key_id", str(key_id))
    types = _normalize_artifact_types(normalized, default_types=default_artifact_types)
    normalized["authorized_artifact_types"] = sorted(types)
    normalized["_authorized_artifact_types"] = types
    if "issuer_identity" not in normalized and normalized.get("identity"):
        normalized["issuer_identity"] = normalized["identity"]
    return normalized


def load_typed_registry(
    path: str | Path,
    *,
    default_artifact_types: frozenset[str] | None = None,
    section_keys: tuple[str, ...] = ("issuers", "keys", "signers", "attestors"),
) -> dict[str, Any]:
    """Load a typed AKTA trust registry (YAML/JSON).

    Entry schema (authoritative fields):
      key_id, public key material, authorized_artifact_types, issuer_identity,
      tenant/institution, status, valid_from/until, replacement_key_id,
      revocation_reason.

    Multi-role keys are allowed only via explicit ``authorized_artifact_types``.
    """
    registry_path = Path(path)
    if not registry_path.is_file():
        return {
            "version": None,
            "keys": {},
            "revoked_key_ids": [],
            "source": str(registry_path),
            "default_artifact_types": sorted(default_artifact_types or ()),
        }

    raw = registry_path.read_text(encoding="utf-8")
    if registry_path.suffix.lower() == ".json":
        data = json.loads(raw) or {}
    else:
        data = yaml.safe_load(raw) or {}

    file_defaults = _normalize_artifact_types(
        {"authorized_artifact_types": data.get("default_authorized_artifact_types")},
        default_types=default_artifact_types,
    )
    if not file_defaults and default_artifact_types:
        file_defaults = frozenset(default_artifact_types)

    keys: dict[str, dict[str, Any]] = {}
    revoked: set[str] = set(str(x) for x in (data.get("revoked_key_ids") or []))

    for section in section_keys:
        section_data = data.get(section) or {}
        if not isinstance(section_data, dict):
            continue
        for key_id, entry in section_data.items():
            if isinstance(entry, str):
                entry = {"public_key_ref": entry}
            if not isinstance(entry, dict):
                continue
            normalized = _normalize_registry_entry(
                str(key_id),
                entry,
                default_artifact_types=file_defaults,
            )
            if _entry_status(normalized) == "revoked":
                revoked.add(str(key_id))
                if normalized.get("public_key_ref"):
                    revoked.add(str(normalized["public_key_ref"]))
            keys[str(key_id)] = normalized
            ref = normalized.get("public_key_ref")
            if ref:
                keys[str(ref)] = normalized

    return {
        "version": data.get("version"),
        "keys": keys,
        "revoked_key_ids": sorted(revoked),
        "source": str(registry_path.resolve()),
        "default_artifact_types": sorted(file_defaults),
        "raw": data,
    }


def load_issuer_registry(path: str | Path) -> dict[str, Any]:
    """Load a grant-issuer registry (backward-compatible name)."""
    return load_typed_registry(
        path,
        default_artifact_types=frozenset({ArtifactType.SCOPE_GRANT.value}),
        section_keys=("issuers", "keys", "signers"),
    )


def load_status_attestation_registry(path: str | Path) -> dict[str, Any]:
    return load_typed_registry(
        path,
        default_artifact_types=frozenset({ArtifactType.SCOPE_GRANT_STATUS.value}),
        section_keys=("attestors", "issuers", "keys", "signers"),
    )


def load_manifest_signer_registry(path: str | Path) -> dict[str, Any]:
    return load_typed_registry(
        path,
        default_artifact_types=frozenset(
            {ArtifactType.SCOPE_AUTHORIZATION_MANIFEST.value}
        ),
        section_keys=("signers", "issuers", "keys"),
    )


def load_reviewer_decision_registry(path: str | Path) -> dict[str, Any]:
    """Optional reviewer registry — never auto-used as grant-issuer trust."""
    return load_typed_registry(
        path,
        default_artifact_types=frozenset({ArtifactType.REVIEWER_DECISION.value}),
        section_keys=("reviewers", "keys", "issuers"),
    )


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
    required_artifact_type: str | None = None,
) -> dict[str, Any]:
    """Build a verifier trust_store dict consumed by ``scope_grant_verifier``."""
    base = base_dir or _AKTA_ROOT / "policy"
    keys = dict(registry.get("keys") or {})
    revoked = set(str(x) for x in (registry.get("revoked_key_ids") or []))
    loaded_keys: dict[str, dict[str, Any]] = {}
    artifact_type = required_artifact_type or (
        (registry.get("default_artifact_types") or [None])[0]
        if registry.get("default_artifact_types")
        else None
    )

    for key_id, entry in keys.items():
        enriched = dict(entry)
        if "_authorized_artifact_types" not in enriched:
            enriched["_authorized_artifact_types"] = _normalize_artifact_types(
                enriched,
                default_types=frozenset(registry.get("default_artifact_types") or ()),
            )
            enriched["authorized_artifact_types"] = sorted(
                enriched["_authorized_artifact_types"]
            )
        try:
            public_key = _load_ed25519_public_key(enriched, base_dir=base)
            pem = None
            if enriched.get("public_key_pem"):
                pem = str(enriched["public_key_pem"])
            elif enriched.get("public_key_file") or enriched.get("public_key_path"):
                path_value = enriched.get("public_key_file") or enriched.get(
                    "public_key_path"
                )
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
            loaded_keys[str(key_id)] = enriched

    def _verify(payload: dict[str, Any], hash_field: str, signature: str) -> bool:
        issuer = payload.get("issuer") or {}
        key_id = (
            issuer.get("issuer_key_id")
            or payload.get("attestation_key_id")
            or payload.get("issuer_key_id")
            or payload.get("manifest_signature_key_id")
        )
        if not key_id:
            return False
        if str(key_id) in revoked:
            return False
        entry = loaded_keys.get(str(key_id))
        if entry is None:
            return False
        if not _entry_usable(entry, required_artifact_type=artifact_type):
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

    return {
        "keys": loaded_keys,
        "revoked_key_ids": sorted(revoked),
        "sources": list(
            registry.get("sources")
            or ([registry.get("source")] if registry.get("source") else [])
        ),
        "required_artifact_type": artifact_type,
        "verify": _verify,
    }


def _policy_dir(policy_dir: Path | None) -> Path:
    return Path(policy_dir) if policy_dir else _AKTA_ROOT / "policy"


def _env_path(*names: str) -> Path | None:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return Path(value)
    return None


def resolve_grant_issuer_trust_store(
    *,
    policy_dir: str | Path | None = None,
    explicit: dict[str, Any] | None = None,
    require_keys: bool = False,
) -> dict[str, Any] | None:
    """Resolve grant-issuer trust store (signatures on scope grants)."""
    if explicit is not None:
        if "verify" not in explicit and explicit.get("keys") is not None:
            return build_trust_store(
                explicit,
                base_dir=_policy_dir(Path(policy_dir) if policy_dir else None),
                required_artifact_type=ArtifactType.SCOPE_GRANT.value,
            )
        return explicit

    base = _policy_dir(Path(policy_dir) if policy_dir else None)
    candidates: list[Path] = []
    env = _env_path("AKTA_GRANT_ISSUER_REGISTRY", "AKTA_TRUST_STORE_PATH", "AKTA_ISSUER_KEY_REGISTRY")
    if env is not None:
        candidates.append(env)
    candidates.append(base / GRANT_ISSUER_REGISTRY_NAME)

    parts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            part = load_issuer_registry(candidate)
            parts.append(
                build_trust_store(
                    part,
                    base_dir=candidate.parent,
                    required_artifact_type=ArtifactType.SCOPE_GRANT.value,
                )
            )

    if not parts:
        if require_keys:
            return build_trust_store(
                {"keys": {}, "revoked_key_ids": []},
                required_artifact_type=ArtifactType.SCOPE_GRANT.value,
            )
        return None
    return _merge_built_stores(parts, required_artifact_type=ArtifactType.SCOPE_GRANT.value)


def resolve_status_attestation_trust_store(
    *,
    policy_dir: str | Path | None = None,
    explicit: dict[str, Any] | None = None,
    require_keys: bool = False,
) -> dict[str, Any] | None:
    if explicit is not None:
        if "verify" not in explicit and explicit.get("keys") is not None:
            return build_trust_store(
                explicit,
                base_dir=_policy_dir(Path(policy_dir) if policy_dir else None),
                required_artifact_type=ArtifactType.SCOPE_GRANT_STATUS.value,
            )
        return explicit

    base = _policy_dir(Path(policy_dir) if policy_dir else None)
    candidates: list[Path] = []
    env = _env_path("AKTA_STATUS_ATTESTATION_REGISTRY")
    if env is not None:
        candidates.append(env)
    candidates.append(base / STATUS_ATTESTATION_REGISTRY_NAME)

    parts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            part = load_status_attestation_registry(candidate)
            parts.append(
                build_trust_store(
                    part,
                    base_dir=candidate.parent,
                    required_artifact_type=ArtifactType.SCOPE_GRANT_STATUS.value,
                )
            )

    if not parts:
        if require_keys:
            return build_trust_store(
                {"keys": {}, "revoked_key_ids": []},
                required_artifact_type=ArtifactType.SCOPE_GRANT_STATUS.value,
            )
        return None
    return _merge_built_stores(
        parts, required_artifact_type=ArtifactType.SCOPE_GRANT_STATUS.value
    )


def resolve_manifest_signer_trust_store(
    *,
    policy_dir: str | Path | None = None,
    explicit: dict[str, Any] | None = None,
    require_keys: bool = False,
) -> dict[str, Any] | None:
    """Resolve manifest-signer registry (wired in Phase B WS5)."""
    if explicit is not None:
        if "verify" not in explicit and explicit.get("keys") is not None:
            return build_trust_store(
                explicit,
                base_dir=_policy_dir(Path(policy_dir) if policy_dir else None),
                required_artifact_type=ArtifactType.SCOPE_AUTHORIZATION_MANIFEST.value,
            )
        return explicit

    base = _policy_dir(Path(policy_dir) if policy_dir else None)
    candidates: list[Path] = []
    env = _env_path("AKTA_MANIFEST_SIGNER_REGISTRY")
    if env is not None:
        candidates.append(env)
    candidates.append(base / MANIFEST_SIGNER_REGISTRY_NAME)

    parts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            part = load_manifest_signer_registry(candidate)
            parts.append(
                build_trust_store(
                    part,
                    base_dir=candidate.parent,
                    required_artifact_type=ArtifactType.SCOPE_AUTHORIZATION_MANIFEST.value,
                )
            )

    if not parts:
        if require_keys:
            return build_trust_store(
                {"keys": {}, "revoked_key_ids": []},
                required_artifact_type=ArtifactType.SCOPE_AUTHORIZATION_MANIFEST.value,
            )
        return None
    return _merge_built_stores(
        parts,
        required_artifact_type=ArtifactType.SCOPE_AUTHORIZATION_MANIFEST.value,
    )


def _merge_built_stores(
    parts: list[dict[str, Any]],
    *,
    required_artifact_type: str | None,
) -> dict[str, Any]:
    keys: dict[str, dict[str, Any]] = {}
    revoked: set[str] = set()
    sources: list[str] = []
    for part in parts:
        sources.extend(str(s) for s in (part.get("sources") or []) if s)
        revoked.update(str(x) for x in (part.get("revoked_key_ids") or []))
        for key_id, entry in (part.get("keys") or {}).items():
            keys[str(key_id)] = dict(entry)

    def _verify(payload: dict[str, Any], hash_field: str, signature: str) -> bool:
        issuer = payload.get("issuer") or {}
        key_id = (
            issuer.get("issuer_key_id")
            or payload.get("attestation_key_id")
            or payload.get("issuer_key_id")
            or payload.get("manifest_signature_key_id")
        )
        if not key_id or str(key_id) in revoked:
            return False
        entry = keys.get(str(key_id))
        if entry is None or not _entry_usable(
            entry, required_artifact_type=required_artifact_type
        ):
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

    return {
        "keys": keys,
        "revoked_key_ids": sorted(revoked),
        "sources": sources,
        "required_artifact_type": required_artifact_type,
        "verify": _verify,
    }


def resolve_trust_store(
    *,
    policy_dir: str | Path | None = None,
    explicit: dict[str, Any] | None = None,
    require_keys: bool = False,
) -> dict[str, Any] | None:
    """Resolve grant-issuer trust store (primary alias for grant authentication).

    Does **not** auto-import SCOPE ``reviewer_key_registry.yaml`` or the local
    ``reviewer_decision_registry.yaml`` into grant-issuer keys.
    """
    return resolve_grant_issuer_trust_store(
        policy_dir=policy_dir,
        explicit=explicit,
        require_keys=require_keys,
    )


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
    required = store.get("required_artifact_type")
    for key_id, entry in keys.items():
        if str(key_id) in revoked:
            continue
        if (
            isinstance(entry, dict)
            and _entry_usable(entry, required_artifact_type=required)
            and entry.get("_public_key") is not None
        ):
            return False
    return True


__all__ = [
    "ArtifactType",
    "GRANT_ISSUER_REGISTRY_NAME",
    "LEGACY_ISSUER_REGISTRY_NAME",
    "MANIFEST_SIGNER_REGISTRY_NAME",
    "REVIEWER_DECISION_REGISTRY_NAME",
    "STATUS_ATTESTATION_REGISTRY_NAME",
    "SUPPORTED_ALGORITHMS",
    "build_trust_store",
    "entry_within_validity",
    "generate_test_keypair",
    "institutional_registry_is_empty",
    "load_issuer_registry",
    "load_manifest_signer_registry",
    "load_reviewer_decision_registry",
    "load_status_attestation_registry",
    "load_typed_registry",
    "merge_registries",
    "resolve_grant_issuer_trust_store",
    "resolve_manifest_signer_trust_store",
    "resolve_status_attestation_trust_store",
    "resolve_trust_store",
    "sign_payload_hash_ed25519",
]
