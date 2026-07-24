"""Effective policy manifest generation and binding (directive §5 / WS11 / P1-15)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

import yaml

from akta.hash import hash_file_content, hash_object
from akta.policy_integrity import (
    ED25519_ALGORITHM,
    HMAC_ALGORITHM,
    _load_manifest,
    compute_file_hash,
    is_production_mode,
    require_signed_policy,
)

EFFECTIVE_MANIFEST_FILENAME = "effective_policy_manifest.json"
EFFECTIVE_MANIFEST_VERSION = "akta-effective-policy-v1.2"

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
    # WS11 / P1-15 provenance expansions
    "shared_contracts_pin.json",
    "scope_grant_issuer_registry.yaml",
    "scope_status_attestation_registry.yaml",
    "scope_policy_manifest_signer_registry.yaml",
    "release_pins.yaml",
    "runtime_capability_mapping.yaml",
)

# P1-15: mandatory in release/production — never listed as missing_optional_inputs.
MANDATORY_RELEASE_INPUTS: frozenset[str] = frozenset({
    "shared_contracts_pin.json",
    "scope_grant_issuer_registry.yaml",
    "scope_status_attestation_registry.yaml",
    "scope_policy_manifest_signer_registry.yaml",
    "release_pins.yaml",
    "runtime_capability_mapping.yaml",
    "scope_compatibility_manifest.json",
})

RELEASE_STRICT_PROFILES = frozenset({
    "release",
    "production",
    "institutional",
    "institutional_release",
})

# Schema / registry names folded into effective-policy body + policy_binding_block.
SCHEMA_HASH_KEYS = (
    "envelope_schema_hash",
    "grant_schema_hash",
    "grant_status_schema_hash",
)

REGISTRY_INPUT_NAMES = (
    "scope_grant_issuer_registry.yaml",
    "scope_status_attestation_registry.yaml",
    "scope_policy_manifest_signer_registry.yaml",
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
            or data.get("pin_version")
            or data.get("manifest_version")
            or "unknown"
        )
    return "unknown"


def effective_policy_strict_mode(*, integrity_mode: str | None = None) -> bool:
    """True when release/production provenance rules apply (P1-15)."""
    if is_production_mode() or require_signed_policy():
        return True
    if os.environ.get("AKTA_VERIFY_EFFECTIVE_POLICY", "").lower() in ("1", "true", "yes"):
        return True
    profile = os.environ.get("AKTA_RELEASE_PROFILE", "").strip().lower()
    if profile in RELEASE_STRICT_PROFILES:
        return True
    if integrity_mode == "release_ed25519_signed":
        return True
    return False


def collect_overlay_registry(overlays_dir: Path | None) -> dict[str, Any]:
    if overlays_dir is None or not overlays_dir.is_dir():
        return {"note": OVERLAY_REGISTRY_NOTE, "overlays": {}}
    overlays: dict[str, str] = {}
    for path in sorted(overlays_dir.glob("*.yaml")):
        overlays[path.name] = compute_file_hash(path)
    return {"note": OVERLAY_REGISTRY_NOTE, "overlays": overlays}


def _load_shared_contracts_pin(policy_dir: Path) -> dict[str, Any]:
    path = policy_dir / "shared_contracts_pin.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _shared_contract_provenance(policy_dir: Path) -> dict[str, Any]:
    """Shared contract version + release/schema hashes for effective policy body."""
    pin = _load_shared_contracts_pin(policy_dir)
    provenance: dict[str, Any] = {
        "package": pin.get("package") or "scientific-authorization-contracts",
        "package_version": pin.get("package_version"),
        "release_artifact_hash": pin.get("release_artifact_hash"),
        "envelope_schema_version": pin.get("envelope_schema_version"),
        "envelope_schema_hash": pin.get("envelope_schema_hash"),
        "grant_schema_version": pin.get("grant_schema_version"),
        "grant_schema_hash": pin.get("grant_schema_hash"),
        "grant_status_schema_hash": pin.get("grant_status_schema_hash"),
    }
    # Prefer live installed package when available (fail soft for offline pin-only).
    try:
        from akta.shared_contracts import (
            contracts_package_version,
            grant_schema_hash,
            grant_schema_version,
            release_artifact_hash,
            shared_contract_report,
        )

        report = shared_contract_report()
        provenance["package_version"] = contracts_package_version()
        provenance["release_artifact_hash"] = release_artifact_hash()
        provenance["envelope_schema_version"] = report.get("envelope_schema_version")
        provenance["envelope_schema_hash"] = report.get("envelope_schema_hash")
        provenance["grant_schema_version"] = grant_schema_version()
        provenance["grant_schema_hash"] = grant_schema_hash()
        if pin.get("grant_status_schema_hash"):
            provenance["grant_status_schema_hash"] = pin["grant_status_schema_hash"]
    except Exception:
        pass
    return {k: v for k, v in provenance.items() if v is not None}


def _schema_hashes_from_provenance(provenance: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in SCHEMA_HASH_KEYS:
        value = provenance.get(key)
        if value:
            out[key] = str(value)
    return out


def _registry_hashes(files: dict[str, str]) -> dict[str, str]:
    return {name: files[name] for name in REGISTRY_INPUT_NAMES if name in files}


def _overlay_aggregate_hash(overlay_registry: dict[str, Any]) -> str | None:
    overlays = overlay_registry.get("overlays") or {}
    if not overlays:
        return None
    return hash_object(overlays)


def _partition_missing(missing: list[str]) -> tuple[list[str], list[str]]:
    """Split missing inputs into mandatory (release) vs optional."""
    mandatory = sorted(name for name in missing if name in MANDATORY_RELEASE_INPUTS)
    optional = sorted(name for name in missing if name not in MANDATORY_RELEASE_INPUTS)
    return mandatory, optional


def _resolve_hmac_key_bytes(explicit: bytes | str | None = None) -> bytes | None:
    if explicit is not None:
        return explicit if isinstance(explicit, bytes) else explicit.encode("utf-8")
    key_env = os.environ.get("AKTA_POLICY_HMAC_KEY")
    if key_env:
        return key_env.encode("utf-8")
    return None


def _resolve_ed25519_private_key(explicit: bytes | None = None) -> bytes | None:
    if explicit is not None:
        return explicit
    raw = os.environ.get("AKTA_POLICY_SIGNING_KEY", "").strip()
    if not raw:
        return None
    if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
        return bytes.fromhex(raw)
    try:
        decoded = base64.b64decode(raw)
        if len(decoded) in (32, 64):
            return decoded
    except ValueError:
        pass
    return None


def _signing_payload(manifest_hash: str) -> bytes:
    """Canonical bytes covered by the effective-policy signature."""
    return manifest_hash.encode("utf-8")


def sign_effective_policy_manifest(
    manifest: dict[str, Any],
    *,
    private_key: bytes | None = None,
    hmac_key: bytes | str | None = None,
    key_id: str | None = None,
) -> dict[str, Any]:
    """Attach Ed25519 or HMAC signature over ``manifest_hash`` (P1-15)."""
    out = dict(manifest)
    manifest_hash = str(out.get("manifest_hash") or "")
    if not manifest_hash:
        raise ValueError("effective policy manifest_hash required before signing")
    payload = _signing_payload(manifest_hash)

    ed_key = _resolve_ed25519_private_key(private_key)
    if ed_key is not None:
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError as exc:
            from akta.errors import PolicyError

            raise PolicyError(
                "Ed25519 signing requires cryptography package; "
                "pip install akta-protocol[security]"
            ) from exc
        if len(ed_key) == 32:
            private = Ed25519PrivateKey.from_private_bytes(ed_key)
        elif len(ed_key) == 64:
            private = Ed25519PrivateKey.from_private_bytes(ed_key[:32])
        else:
            from akta.errors import PolicyError

            raise PolicyError("Ed25519 private key must be 32 or 64 bytes")
        signature = private.sign(payload)
        public_bytes = private.public_key().public_bytes_raw()
        out["signed_payload_hash"] = manifest_hash
        out["signature"] = {
            "algorithm": ED25519_ALGORITHM,
            "value": base64.b64encode(signature).decode("ascii"),
            "public_key": base64.b64encode(public_bytes).decode("ascii"),
            "key_id": key_id or out.get("signing_key_id") or "effective-policy-primary",
        }
        return out

    mac_key = _resolve_hmac_key_bytes(hmac_key)
    if mac_key is None:
        return out

    digest = hmac.new(mac_key, payload, hashlib.sha256).hexdigest()
    out["signed_payload_hash"] = manifest_hash
    out["signature"] = {
        "algorithm": HMAC_ALGORITHM,
        "value": digest,
        "key_id": key_id or out.get("signing_key_id"),
    }
    return out


def verify_effective_policy_signature(
    manifest: dict[str, Any],
    *,
    policy_dir: str | Path | None = None,
    hmac_key: bytes | str | None = None,
) -> None:
    """Verify the stored effective-policy signature; raise PolicyError on failure."""
    from akta.errors import PolicyError

    sig = manifest.get("signature")
    if not isinstance(sig, dict) or not sig.get("value"):
        raise PolicyError(
            "effective policy manifest missing signature; "
            "recomputing an unsigned manifest is insufficient for production provenance"
        )

    manifest_hash = str(manifest.get("manifest_hash") or "")
    if not manifest_hash:
        raise PolicyError("effective policy manifest missing manifest_hash")

    signed_payload = manifest.get("signed_payload_hash")
    if signed_payload is not None and signed_payload != manifest_hash:
        raise PolicyError(
            "effective policy signed_payload_hash must equal manifest_hash"
        )

    algo = sig.get("algorithm")
    payload = _signing_payload(manifest_hash)

    if algo == HMAC_ALGORITHM:
        mac_key = _resolve_hmac_key_bytes(hmac_key)
        if mac_key is None:
            raise PolicyError(
                "effective policy HMAC verification requires AKTA_POLICY_HMAC_KEY"
            )
        expected = hmac.new(mac_key, payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, str(sig.get("value") or "")):
            raise PolicyError("effective policy HMAC signature verification failed")
        return

    if algo == ED25519_ALGORITHM:
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        except ImportError as exc:
            raise PolicyError(
                "Ed25519 verification requires cryptography package; "
                "pip install akta-protocol[security]"
            ) from exc

        try:
            signature = base64.b64decode(str(sig.get("value") or ""))
        except ValueError as exc:
            raise PolicyError(f"Invalid Ed25519 signature encoding: {exc}") from exc

        keys: list[bytes] = []
        if sig.get("public_key"):
            raw = str(sig["public_key"]).strip()
            try:
                if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
                    keys.append(bytes.fromhex(raw))
                else:
                    keys.append(base64.b64decode(raw))
            except ValueError as exc:
                raise PolicyError(f"Invalid Ed25519 public key encoding: {exc}") from exc

        env_key = os.environ.get("AKTA_POLICY_PUBLIC_KEY")
        if env_key:
            cleaned = env_key.strip()
            try:
                if len(cleaned) == 64 and all(
                    c in "0123456789abcdefABCDEF" for c in cleaned
                ):
                    keys.append(bytes.fromhex(cleaned))
                else:
                    keys.append(base64.b64decode(cleaned))
            except ValueError as exc:
                raise PolicyError(f"Invalid Ed25519 public key encoding: {exc}") from exc

        if policy_dir is not None:
            try:
                from akta.policy_signing import load_release_key_registry

                registry = load_release_key_registry(Path(policy_dir))
                key_id = sig.get("key_id")
                for entry in registry.get("keys") or []:
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("status") not in (None, "active"):
                        continue
                    if key_id and entry.get("key_id") != key_id:
                        continue
                    pk = entry.get("public_key")
                    if pk:
                        keys.append(base64.b64decode(str(pk)))
            except Exception:
                pass

        if not keys:
            raise PolicyError(
                "effective policy Ed25519 verification requires public key "
                "(signature.public_key, AKTA_POLICY_PUBLIC_KEY, or release_keys.yaml)"
            )

        last_error: Exception | None = None
        for key_bytes in keys:
            try:
                public_key = Ed25519PublicKey.from_public_bytes(key_bytes)
                public_key.verify(signature, payload)
                return
            except (InvalidSignature, ValueError) as exc:
                last_error = exc
                continue
        raise PolicyError(
            "effective policy Ed25519 signature verification failed"
        ) from last_error

    raise PolicyError(f"Unsupported effective policy signature algorithm: {algo!r}")


def build_effective_policy_manifest(
    policy_dir: str | Path,
    *,
    overlays_dir: str | Path | None = None,
    integrity_mode: str = "dev_unsigned",
    strict_mandatory: bool | None = None,
) -> dict[str, Any]:
    """Build effective_policy_manifest covering available policy inputs.

    Mandatory release inputs (shared contract pin, three registries, release pins,
    runtime capability mapping, compatibility manifest) are never recorded under
    ``missing_optional_inputs``. In release/production modes they must be present.
    """
    from akta.errors import PolicyError

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

    missing_mandatory, missing_optional = _partition_missing(missing)
    if strict_mandatory is None:
        strict_mandatory = effective_policy_strict_mode(integrity_mode=integrity_mode)
    if strict_mandatory and missing_mandatory:
        raise PolicyError(
            "effective policy missing mandatory release inputs: "
            + ", ".join(missing_mandatory)
        )

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
    shared_contracts = _shared_contract_provenance(policy_dir)
    schema_hashes = _schema_hashes_from_provenance(shared_contracts)
    registry_hashes = _registry_hashes(files)
    overlay_hash = _overlay_aggregate_hash(overlay_registry)
    release_pins_hash = files.get("release_pins.yaml")
    runtime_capability_mapping_hash = files.get("runtime_capability_mapping.yaml")
    compatibility_manifest_hash = files.get("scope_compatibility_manifest.json")

    effective_policy_hash = hash_object({
        "files": files,
        "file_versions": file_versions,
        "overlay_registry": overlay_registry,
        "bundle_version": bundle_version,
        "shared_contracts": shared_contracts,
        "schema_hashes": schema_hashes,
        "registry_hashes": registry_hashes,
        "release_pins_hash": release_pins_hash,
        "runtime_capability_mapping_hash": runtime_capability_mapping_hash,
        "compatibility_manifest_hash": compatibility_manifest_hash,
    })
    # Canonical JSON for manifest_hash excludes hash + signature fields.
    # integrity_mode is recorded on the artifact but excluded from the hash so
    # HMAC vs unsigned load paths do not falsely flag provenance drift.
    body_for_hash = {
        "manifest_version": EFFECTIVE_MANIFEST_VERSION,
        "bundle_version": bundle_version,
        "signing_key_id": signing_key_id,
        "files": files,
        "file_versions": file_versions,
        "overlay_registry": overlay_registry,
        "missing_optional_inputs": missing_optional,
        "missing_mandatory_inputs": missing_mandatory,
        "shared_contracts": shared_contracts,
        "schema_hashes": schema_hashes,
        "registry_hashes": registry_hashes,
        "release_pins_hash": release_pins_hash,
        "runtime_capability_mapping_hash": runtime_capability_mapping_hash,
        "compatibility_manifest_hash": compatibility_manifest_hash,
        "overlay_hash": overlay_hash,
        "policy_manifest_signature": {
            "algorithm": sig.get("algorithm"),
            "key_id": signing_key_id,
            "present": bool(sig),
        },
    }
    manifest_hash = hash_object(body_for_hash)

    return {
        **body_for_hash,
        "integrity_mode": integrity_mode,
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
    sign: bool | None = None,
    private_key: bytes | None = None,
    hmac_key: bytes | str | None = None,
) -> Path:
    """Write effective_policy_manifest.json under policy_dir.

    When ``sign`` is True, or signing material is available via args/env, the
    stored manifest is signed. Production provenance requires a signed store.
    """
    policy_dir = Path(policy_dir)
    # Build without strict raise so regenerators can still write partial trees in
    # non-production; verify/require enforce mandatory inputs in strict modes.
    manifest = build_effective_policy_manifest(
        policy_dir,
        overlays_dir=overlays_dir,
        integrity_mode=integrity_mode,
        strict_mandatory=False,
    )
    should_sign = sign
    if should_sign is None:
        should_sign = (
            private_key is not None
            or hmac_key is not None
            or _resolve_ed25519_private_key() is not None
            or _resolve_hmac_key_bytes() is not None
            or effective_policy_strict_mode(integrity_mode=integrity_mode)
        )
    if should_sign:
        if (
            private_key is None
            and hmac_key is None
            and _resolve_ed25519_private_key() is None
            and _resolve_hmac_key_bytes() is None
        ):
            # Strict mode without keys: leave unsigned; verify will fail closed.
            pass
        else:
            manifest = sign_effective_policy_manifest(
                manifest,
                private_key=private_key,
                hmac_key=hmac_key,
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
    require_signature: bool | None = None,
) -> dict[str, Any]:
    """Rebuild effective policy from current files and compare to stored (P0-G / P1-15).

    Does NOT trust hashes copied from effective_policy_manifest.json without
    recomputation. In release/production modes, a stored **signed** manifest is
    required — recomputing an unsigned manifest is insufficient for provenance.
    """
    from akta.errors import PolicyError

    policy_dir = Path(policy_dir)
    strict = effective_policy_strict_mode(integrity_mode=integrity_mode)
    if require_signature is None:
        require_signature = strict

    try:
        recomputed = build_effective_policy_manifest(
            policy_dir,
            overlays_dir=overlays_dir,
            integrity_mode=integrity_mode,
            strict_mandatory=strict,
        )
    except PolicyError as exc:
        return {
            "ok": False,
            "recomputed": None,
            "stored": stored if stored is not None else load_effective_policy_manifest(policy_dir),
            "errors": [str(exc)],
        }

    stored_manifest = stored if stored is not None else load_effective_policy_manifest(policy_dir)
    errors: list[str] = []

    if stored_manifest is None:
        if require_signature or strict:
            return {
                "ok": False,
                "recomputed": recomputed,
                "stored": None,
                "errors": [
                    "no stored effective_policy_manifest; "
                    "recomputing an unsigned manifest is insufficient for "
                    "production provenance"
                ],
            }
        return {
            "ok": True,
            "recomputed": recomputed,
            "stored": None,
            "errors": [],
            "note": "no stored effective_policy_manifest; recomputed accepted",
        }

    if require_signature:
        try:
            verify_effective_policy_signature(stored_manifest, policy_dir=policy_dir)
        except PolicyError as exc:
            errors.append(str(exc))

    # Mandatory inputs must never appear under missing_optional_inputs.
    stored_optional = stored_manifest.get("missing_optional_inputs") or []
    leaked = sorted(
        name for name in stored_optional if name in MANDATORY_RELEASE_INPUTS
    )
    if leaked:
        errors.append(
            "mandatory release inputs incorrectly listed in missing_optional_inputs: "
            + ", ".join(leaked)
        )

    stored_mandatory = stored_manifest.get("missing_mandatory_inputs") or []
    if strict and stored_mandatory:
        errors.append(
            "stored effective policy missing mandatory release inputs: "
            + ", ".join(str(x) for x in stored_mandatory)
        )
    if strict and recomputed.get("missing_mandatory_inputs"):
        errors.append(
            "recomputed effective policy missing mandatory release inputs: "
            + ", ".join(str(x) for x in recomputed["missing_mandatory_inputs"])
        )

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

    for key in ("schema_hashes", "registry_hashes", "shared_contracts"):
        if (stored_manifest.get(key) or {}) != (recomputed.get(key) or {}):
            errors.append(f"effective policy {key} drift")

    # Mutating critical inputs after manifest generation must fail.
    critical = set(MANDATORY_RELEASE_INPUTS) | {
        "default_tool_registry.yaml",
        "tool_to_requested_scope.yaml",
        "scope_grant_override_rules.yaml",
        "structured_action_schema.yaml",
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
    # Prefer the stored signed artifact in strict modes; recomputed alone is not
    # production provenance.
    if effective_policy_strict_mode(integrity_mode=integrity_mode) and result.get("stored"):
        return result["stored"]
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
    shared_contract_release_hash: str | None = None,
    issuer_registry_hash: str | None = None,
    status_attestation_registry_hash: str | None = None,
    policy_manifest_signer_registry_hash: str | None = None,
    release_pins_hash: str | None = None,
    runtime_capability_mapping_hash: str | None = None,
    compatibility_manifest_hash: str | None = None,
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
        "schema_hashes": dict(schema_hashes or {}),
        "overlay_hash": overlay_hash,
        "shared_contract_release_hash": shared_contract_release_hash,
        "issuer_registry_hash": issuer_registry_hash,
        "status_attestation_registry_hash": status_attestation_registry_hash,
        "policy_manifest_signer_registry_hash": policy_manifest_signer_registry_hash,
        "release_pins_hash": release_pins_hash,
        "runtime_capability_mapping_hash": runtime_capability_mapping_hash,
        "compatibility_manifest_hash": compatibility_manifest_hash,
    }
    return block


def binding_from_effective_manifest(
    *,
    bundle_version: str,
    integrity_mode: str,
    signing_key_id: str | None,
    file_versions: dict[str, str],
    effective: dict[str, Any],
    policy_hash_fallback: str = "",
) -> dict[str, Any]:
    """Populate every policy_binding_block field from a recomputed effective manifest."""
    shared = effective.get("shared_contracts") or {}
    registries = effective.get("registry_hashes") or {}
    return policy_binding_block(
        bundle_version=bundle_version,
        effective_policy_hash=str(
            effective.get("effective_policy_hash") or policy_hash_fallback
        ),
        manifest_hash=str(effective.get("manifest_hash") or policy_hash_fallback),
        integrity_mode=integrity_mode,
        signing_key_id=signing_key_id,
        file_versions=file_versions,
        schema_hashes=dict(effective.get("schema_hashes") or {}),
        overlay_hash=effective.get("overlay_hash"),
        release_key_id=signing_key_id,
        shared_contract_release_hash=shared.get("release_artifact_hash"),
        issuer_registry_hash=registries.get("scope_grant_issuer_registry.yaml"),
        status_attestation_registry_hash=registries.get(
            "scope_status_attestation_registry.yaml"
        ),
        policy_manifest_signer_registry_hash=registries.get(
            "scope_policy_manifest_signer_registry.yaml"
        ),
        release_pins_hash=effective.get("release_pins_hash"),
        runtime_capability_mapping_hash=effective.get("runtime_capability_mapping_hash"),
        compatibility_manifest_hash=effective.get("compatibility_manifest_hash"),
    )
