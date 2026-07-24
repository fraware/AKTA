"""Authenticate SCOPE authorization manifests (AKTA 1.2 P0-7 / P0-8).

Accepts embedded-by-reference, authenticated SCOPE fetch, or locally pinned
signed manifests. Grant ``provenance.scope_trust_root_hash`` must equal a
verified manifest hash. Cache is keyed by hash and refreshed on key revocation.

Verification uses the exact unsigned body bytes (canonical hash) — the manifest
is never transformed after signing. Field expectations align with the canonical
SCOPE authorization-manifest vocabulary; nested ``schemas`` / ``vocabularies`` /
``policies`` / ``registries`` maps are accepted when present.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from akta.hash import hash_object
from akta.shared_contracts import (
    CONTRACTS_PACKAGE_VERSION,
    authorization_envelope_schema_hash,
    grant_schema_hash,
    release_artifact_hash,
)
from akta.trust_store import (
    ArtifactType,
    entry_within_validity,
    institutional_registry_is_empty,
    resolve_manifest_signer_trust_store,
)

SUPPORTED_MANIFEST_ALGORITHMS = frozenset({"Ed25519", "ed25519"})

# Signature / envelope fields excluded from the signed body hash.
_MANIFEST_UNSIGNED_FIELDS = frozenset(
    {
        "manifest_hash",
        "signed_payload_hash",
        "manifest_signature",
        "signature",
        "attestation_signature",
    }
)

# Canonical required hash bindings (flat aliases + nested maps).
REQUIRED_MANIFEST_HASH_FIELDS = (
    "shared_contract_release_hash",  # shared contract wheel / release hash
    "authorization_envelope_schema_hash",
    "grant_schema_hash",
    "vocabulary_hash",
    "scope_policy_hash",
    "identity_policy_hash",
    "rbac_hash",
    "delegation_policy_hash",
    "issuer_registry_hash",  # grant issuer registry
    "status_attestor_registry_hash",
    "manifest_signer_registry_hash",
    "runtime_evaluator_registry_hash",
)

# Nested canonical paths: (top_level_key, nested_key, flat_alias)
_NESTED_HASH_ALIASES: tuple[tuple[str, str, str], ...] = (
    ("shared_contract", "wheel_hash", "shared_contract_release_hash"),
    ("shared_contract", "release_hash", "shared_contract_release_hash"),
    ("schemas", "authorization_envelope", "authorization_envelope_schema_hash"),
    ("schemas", "grant", "grant_schema_hash"),
    ("schemas", "grant_status", "grant_status_schema_hash"),
    ("vocabularies", "capability", "vocabulary_hash"),
    ("vocabularies", "family", "vocabulary_hash"),
    ("policies", "scope", "scope_policy_hash"),
    ("policies", "identity", "identity_policy_hash"),
    ("policies", "rbac", "rbac_hash"),
    ("policies", "delegation", "delegation_policy_hash"),
    ("registries", "grant_issuer", "issuer_registry_hash"),
    ("registries", "status_attestor", "status_attestor_registry_hash"),
    ("registries", "manifest_signer", "manifest_signer_registry_hash"),
    ("registries", "runtime_evaluator", "runtime_evaluator_registry_hash"),
)


@dataclass
class ManifestVerificationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest: dict[str, Any] | None = None
    manifest_hash: str | None = None


class _ManifestCache:
    """Hash-keyed cache; entries invalidated when signer keys are revoked."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_hash: dict[str, dict[str, Any]] = {}
        self._signer_revocation_epoch: int = 0

    def get(self, manifest_hash: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._by_hash.get(manifest_hash)
            if entry is None:
                return None
            return dict(entry["manifest"])

    def put(self, manifest_hash: str, manifest: dict[str, Any], *, key_id: str) -> None:
        with self._lock:
            self._by_hash[manifest_hash] = {
                "manifest": dict(manifest),
                "key_id": key_id,
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "revocation_epoch": self._signer_revocation_epoch,
            }

    def invalidate_on_revocation(self, revoked_key_ids: set[str] | frozenset[str]) -> None:
        with self._lock:
            self._signer_revocation_epoch += 1
            drop = [
                h
                for h, entry in self._by_hash.items()
                if entry.get("key_id") in revoked_key_ids
            ]
            for h in drop:
                del self._by_hash[h]

    def clear(self) -> None:
        with self._lock:
            self._by_hash.clear()
            self._signer_revocation_epoch += 1


_CACHE = _ManifestCache()


def clear_manifest_cache() -> None:
    _CACHE.clear()


def invalidate_manifest_cache_for_revoked_keys(
    revoked_key_ids: set[str] | frozenset[str] | list[str],
) -> None:
    _CACHE.invalidate_on_revocation(frozenset(str(x) for x in revoked_key_ids))


def unsigned_manifest_body(manifest: dict[str, Any]) -> dict[str, Any]:
    """Exact unsigned body used for hashing — no post-sign transforms."""
    return {k: v for k, v in manifest.items() if k not in _MANIFEST_UNSIGNED_FIELDS}


def compute_manifest_hash(manifest: dict[str, Any]) -> str:
    """Canonical hash over unsigned manifest body (excludes signature fields)."""
    return hash_object(unsigned_manifest_body(manifest))


def resolve_manifest_hash_field(manifest: dict[str, Any], field_name: str) -> Any:
    """Resolve a required hash from flat alias or nested canonical maps."""
    if manifest.get(field_name):
        return manifest.get(field_name)
    for top, nested, alias in _NESTED_HASH_ALIASES:
        if alias != field_name:
            continue
        container = manifest.get(top)
        if isinstance(container, dict) and container.get(nested):
            return container.get(nested)
    return None


def _missing_required_hash_fields(manifest: dict[str, Any]) -> list[str]:
    return [
        name
        for name in REQUIRED_MANIFEST_HASH_FIELDS
        if not resolve_manifest_hash_field(manifest, name)
    ]


def _fetch_manifest_by_hash(
    manifest_hash: str,
    *,
    endpoint: str | None = None,
    scope_client: Any | None = None,
) -> dict[str, Any] | None:
    """Fetch via ScopeAuthorizationClient (P0-8); no bare urlopen."""
    client = scope_client
    if client is None:
        from akta.scope_client import ScopeAuthorizationClient, ScopeClientConfig

        cfg = ScopeClientConfig.from_env()
        if endpoint:
            cfg.manifest_url = endpoint
        if not cfg.manifest_url:
            return None
        client = ScopeAuthorizationClient(cfg)
    elif endpoint is not None and getattr(client, "config", None) is not None:
        # Temporary endpoint override for this fetch only.
        from akta.scope_client import ScopeAuthorizationClient, ScopeClientConfig

        cfg = ScopeClientConfig(
            manifest_url=endpoint,
            status_url=getattr(client.config, "status_url", None),
            oidc_token=getattr(client.config, "oidc_token", None),
            oidc_token_provider=getattr(client.config, "oidc_token_provider", None),
            mtls_cert_file=getattr(client.config, "mtls_cert_file", None),
            mtls_key_file=getattr(client.config, "mtls_key_file", None),
            ca_bundle=getattr(client.config, "ca_bundle", None),
            verify_tls=getattr(client.config, "verify_tls", True),
            audience=getattr(client.config, "audience", None),
            tenant_id=getattr(client.config, "tenant_id", None),
            timeout_seconds=getattr(client.config, "timeout_seconds", 5.0),
            max_response_bytes=getattr(client.config, "max_response_bytes", 1_048_576),
            max_retries=getattr(client.config, "max_retries", 2),
            require_transport_auth=getattr(
                client.config, "require_transport_auth", False
            ),
            extra_headers=dict(getattr(client.config, "extra_headers", {}) or {}),
        )
        client = ScopeAuthorizationClient(cfg)

    try:
        return dict(client.get_manifest(manifest_hash))
    except Exception:  # noqa: BLE001 — resolve path treats fetch miss as unavailable
        return None


def _load_pinned_manifest(path: str | Path | None = None) -> dict[str, Any] | None:
    env = os.environ.get("AKTA_SCOPE_AUTHORIZATION_MANIFEST_PATH", "").strip()
    candidate = Path(path) if path else (Path(env) if env else None)
    if candidate is None or not candidate.is_file():
        return None
    text = candidate.read_text(encoding="utf-8")
    if candidate.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return data if isinstance(data, dict) else None


def _contract_hash_mismatches(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    declared_version = manifest.get("shared_contract_version") or (
        (manifest.get("shared_contract") or {}).get("version")
        if isinstance(manifest.get("shared_contract"), dict)
        else None
    )
    if declared_version and str(declared_version) != CONTRACTS_PACKAGE_VERSION:
        errors.append(
            f"authorization manifest shared_contract_version mismatch "
            f"({declared_version!r} != {CONTRACTS_PACKAGE_VERSION!r})"
        )
    try:
        expected_release = release_artifact_hash()
    except Exception:  # noqa: BLE001
        expected_release = None
    declared_release = resolve_manifest_hash_field(
        manifest, "shared_contract_release_hash"
    )
    if expected_release and declared_release and declared_release != expected_release:
        errors.append("authorization manifest shared_contract_release_hash mismatch")

    expected_env = authorization_envelope_schema_hash()
    declared_env = resolve_manifest_hash_field(
        manifest, "authorization_envelope_schema_hash"
    )
    if declared_env and declared_env != expected_env:
        errors.append("authorization manifest authorization_envelope_schema_hash mismatch")

    expected_grant = grant_schema_hash()
    declared_grant = resolve_manifest_hash_field(manifest, "grant_schema_hash")
    if declared_grant and declared_grant != expected_grant:
        errors.append("authorization manifest grant_schema_hash mismatch")
    return errors


def _signature_errors(
    manifest: dict[str, Any],
    *,
    trust_store: dict[str, Any] | None,
    require_crypto: bool,
) -> list[str]:
    errors: list[str] = []
    sig = manifest.get("manifest_signature") or manifest.get("signature")
    if not sig:
        errors.append("authorization manifest signature missing")
        return errors

    algo = manifest.get("signature_algorithm") or "Ed25519"
    if str(algo) not in SUPPORTED_MANIFEST_ALGORITHMS:
        errors.append(f"unsupported authorization manifest signature_algorithm: {algo!r}")

    issuer = manifest.get("issuer") or {}
    key_id = (
        issuer.get("issuer_key_id")
        or manifest.get("manifest_signature_key_id")
        or manifest.get("signer_key_id")
    )
    if not key_id:
        errors.append("authorization manifest signer key id missing")
        return errors

    if trust_store is None:
        if require_crypto:
            errors.append("manifest signer trust store required")
        return errors

    if require_crypto and (
        not (trust_store.get("keys") or {}) or institutional_registry_is_empty(trust_store)
    ):
        errors.append("manifest signer trust store has no approved keys")

    revoked = set(trust_store.get("revoked_key_ids") or [])
    if key_id in revoked:
        errors.append(f"revoked authorization manifest signer key: {key_id}")
        invalidate_manifest_cache_for_revoked_keys({str(key_id)})
        return errors

    keys = trust_store.get("keys") or {}
    entry = keys.get(key_id)
    if entry is None:
        errors.append(f"unknown authorization manifest signer key: {key_id}")
        return errors

    status = str(entry.get("status") or "active").lower()
    if status != "active":
        errors.append(f"authorization manifest signer key not active (status={status})")
    if not entry_within_validity(entry):
        errors.append(f"authorization manifest signer key outside validity window: {key_id}")

    allowed = entry.get("_authorized_artifact_types") or set(
        entry.get("authorized_artifact_types") or []
    )
    required = ArtifactType.SCOPE_AUTHORIZATION_MANIFEST.value
    if allowed and required not in allowed:
        errors.append(
            f"signer key {key_id} not authorized for artifact type {required!r}"
        )

    hash_field = "manifest_hash" if "manifest_hash" in manifest else "signed_payload_hash"
    if hash_field not in manifest:
        errors.append("authorization manifest hash missing")
        return errors

    signed_payload = manifest.get("signed_payload_hash")
    if signed_payload is not None and signed_payload != manifest.get(hash_field):
        errors.append("authorization manifest signed_payload_hash must equal manifest_hash")

    verifier = trust_store.get("verify")
    if callable(verifier):
        try:
            if not verifier(manifest, hash_field, str(sig)):
                errors.append("authorization manifest signature invalid")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"authorization manifest signature verification failed: {exc}")
    elif require_crypto:
        errors.append("manifest signer trust store missing verify callback")
    return errors


def verify_authorization_manifest(
    manifest: dict[str, Any],
    *,
    expected_hash: str | None = None,
    trust_store: dict[str, Any] | None = None,
    require_crypto: bool = True,
    use_cache: bool = True,
) -> ManifestVerificationResult:
    """Verify a signed SCOPE authorization manifest over exact signed bytes."""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(manifest, dict) or not manifest:
        return ManifestVerificationResult(ok=False, errors=["authorization manifest empty"])

    # Never mutate the caller's object; hash the exact unsigned body.
    computed = compute_manifest_hash(manifest)
    declared = manifest.get("manifest_hash")
    if declared and declared != computed:
        if require_crypto:
            errors.append(
                f"authorization manifest_hash mismatch ({declared} != {computed})"
            )
        else:
            warnings.append(
                f"authorization manifest_hash mismatch ({declared} != {computed})"
            )
    manifest_hash = declared or computed
    if expected_hash and manifest_hash != expected_hash:
        errors.append(
            f"authorization manifest hash does not match grant trust root "
            f"({manifest_hash} != {expected_hash})"
        )

    if use_cache and not errors:
        cached = _CACHE.get(manifest_hash)
        if cached is not None:
            return ManifestVerificationResult(
                ok=True,
                manifest=cached,
                manifest_hash=manifest_hash,
            )

    for field_name in _missing_required_hash_fields(manifest):
        msg = f"authorization manifest missing {field_name}"
        if require_crypto:
            errors.append(msg)
        else:
            warnings.append(msg)

    errors.extend(_contract_hash_mismatches(manifest))

    resolved_trust = trust_store
    if resolved_trust is None and require_crypto:
        resolved_trust = resolve_manifest_signer_trust_store(require_keys=True)

    errors.extend(
        _signature_errors(
            manifest,
            trust_store=resolved_trust,
            require_crypto=require_crypto,
        )
    )

    ok = not errors
    if ok and use_cache:
        issuer = manifest.get("issuer") or {}
        key_id = str(
            issuer.get("issuer_key_id")
            or manifest.get("manifest_signature_key_id")
            or ""
        )
        stored = dict(manifest)
        stored.setdefault("manifest_hash", manifest_hash)
        _CACHE.put(manifest_hash, stored, key_id=key_id)

    return ManifestVerificationResult(
        ok=ok,
        errors=errors,
        warnings=warnings,
        manifest=dict(manifest) if ok else None,
        manifest_hash=manifest_hash if ok else None,
    )


def resolve_and_verify_authorization_manifest(
    *,
    expected_trust_root_hash: str | None,
    embedded_manifest: dict[str, Any] | None = None,
    pinned_path: str | Path | None = None,
    fetch_endpoint: str | None = None,
    trust_store: dict[str, Any] | None = None,
    require_crypto: bool = True,
    scope_client: Any | None = None,
) -> ManifestVerificationResult:
    """Resolve manifest via cache, embed, pin, or authenticated fetch, then verify."""
    if not expected_trust_root_hash:
        return ManifestVerificationResult(
            ok=False,
            errors=["provenance.scope_trust_root_hash missing"],
        )

    if require_crypto:
        cached = _CACHE.get(expected_trust_root_hash)
        if cached is not None:
            return verify_authorization_manifest(
                cached,
                expected_hash=expected_trust_root_hash,
                trust_store=trust_store,
                require_crypto=require_crypto,
                use_cache=True,
            )

    candidates: list[dict[str, Any]] = []
    if isinstance(embedded_manifest, dict):
        candidates.append(embedded_manifest)
    pinned = _load_pinned_manifest(pinned_path)
    if pinned is not None:
        candidates.append(pinned)
    fetched = _fetch_manifest_by_hash(
        expected_trust_root_hash,
        endpoint=fetch_endpoint,
        scope_client=scope_client,
    )
    if fetched is not None:
        candidates.append(fetched)

    if not candidates:
        return ManifestVerificationResult(
            ok=False,
            errors=[
                "authorization manifest unavailable for trust root "
                f"{expected_trust_root_hash}"
            ],
        )

    last: ManifestVerificationResult | None = None
    for candidate in candidates:
        last = verify_authorization_manifest(
            candidate,
            expected_hash=expected_trust_root_hash,
            trust_store=trust_store,
            require_crypto=require_crypto,
        )
        if last.ok:
            return last
    return last or ManifestVerificationResult(
        ok=False, errors=["authorization manifest verification failed"]
    )


def build_test_authorization_manifest(
    *,
    signer_keys: dict[str, str],
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a signed manifest for tests (uses installed contract hashes)."""
    from akta.trust_store import sign_payload_hash_ed25519

    try:
        vocab_hash = hash_object({"vocabulary": "scientific-authorization-vocab-v1"})
    except Exception:  # noqa: BLE001
        vocab_hash = "sha256:" + ("a" * 64)

    try:
        release_hash = release_artifact_hash()
    except Exception:  # noqa: BLE001
        release_hash = "sha256:" + ("b" * 64)

    # Build unsigned body completely, then hash once — never transform after signing.
    manifest: dict[str, Any] = {
        "manifest_version": "scope-authorization-manifest-v1",
        "created_at": "2026-01-01T00:00:00Z",
        "shared_contract_version": CONTRACTS_PACKAGE_VERSION,
        "shared_contract_release_hash": release_hash,
        "authorization_envelope_schema_hash": authorization_envelope_schema_hash(),
        "grant_schema_hash": grant_schema_hash(),
        "vocabulary_hash": vocab_hash,
        "scope_policy_hash": "sha256:" + ("c" * 64),
        "identity_policy_hash": "sha256:" + ("e" * 64),
        "rbac_hash": "sha256:" + ("f" * 64),
        "delegation_policy_hash": "sha256:" + ("2" * 64),
        "issuer_registry_hash": "sha256:" + ("d" * 64),
        "status_attestor_registry_hash": "sha256:" + ("3" * 64),
        "manifest_signer_registry_hash": "sha256:" + ("4" * 64),
        "runtime_evaluator_registry_hash": "sha256:" + ("5" * 64),
        "domain_overlay_hash": "sha256:" + ("1" * 64),
        "issuer": {
            "issuer_identity": "scope-manifest-signer",
            "issuer_key_id": signer_keys["public_key_ref"],
        },
        "signature_algorithm": "Ed25519",
    }
    if extras:
        # Apply extras before hashing/signing only.
        manifest.update(extras)
    manifest_hash = compute_manifest_hash(manifest)
    signed = dict(manifest)
    signed["manifest_hash"] = manifest_hash
    signed["signed_payload_hash"] = manifest_hash
    priv = Path(signer_keys["private_key_path"]).read_bytes()
    signed["manifest_signature"] = sign_payload_hash_ed25519(priv, manifest_hash)
    return signed
