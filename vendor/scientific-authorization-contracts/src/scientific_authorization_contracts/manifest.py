"""Shared signed scientific-authorization-manifest-v1 helpers (no SCOPE policy loading)."""

from __future__ import annotations

from typing import Any, Mapping

from scientific_authorization_contracts.errors import EnvelopeValidationError
from scientific_authorization_contracts.hashing import compute_hash, verify_hash
from scientific_authorization_contracts.loaders import (
    authorization_schema_provenance,
    load_schema,
    package_version,
)

MANIFEST_VERSION = "scientific-authorization-manifest-v1"


def load_manifest_schema() -> dict[str, Any]:
    return load_schema("authorization_manifest.v1.schema.json")


def build_shared_contract_block() -> dict[str, Any]:
    provenance = authorization_schema_provenance()
    return {
        "package": "scientific-authorization-contracts",
        "version": package_version(),
        "package_hash": provenance.get("contracts_package_hash"),
        "envelope_schema_hash": provenance.get("authorization_schema_hash"),
        "grant_schema_hash": provenance.get("grant_schema_hash"),
        "grant_status_schema_hash": provenance.get("grant_status_schema_hash"),
        "operations_vocab_hash": provenance.get("operations_vocab_hash"),
        "constraint_types_vocab_hash": provenance.get("constraint_types_vocab_hash"),
        "capability_families_vocab_hash": provenance.get("capability_families_vocab_hash"),
        "target_types_vocab_hash": provenance.get("target_types_vocab_hash"),
        "expiration_events_vocab_hash": provenance.get("expiration_events_vocab_hash"),
        "runtime_evaluator_registry_hash": provenance.get(
            "runtime_evaluator_registry_hash"
        ),
    }


def build_manifest_skeleton(
    *,
    schemas: dict[str, Any] | None = None,
    vocabularies: dict[str, Any] | None = None,
    policies: dict[str, Any] | None = None,
    registries: dict[str, Any] | None = None,
    created_at: str | None = None,
    issuer_identity: str | None = None,
) -> dict[str, Any]:
    """
    Assemble an unsigned manifest object with the directive vocabulary.

    SCOPE fills ``policies`` / ``registries`` hashes then signs — no field renames
    after signing.
    """
    body: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "shared_contract": build_shared_contract_block(),
        "schemas": dict(schemas or {}),
        "vocabularies": dict(vocabularies or {}),
        "policies": dict(policies or {}),
        "registries": dict(registries or {}),
    }
    if created_at is not None:
        body["created_at"] = created_at
    if issuer_identity is not None:
        body["issuer"] = {"issuer_identity": issuer_identity}
    return body


def validate_manifest_structure(manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        errors.append(
            f"manifest_version must be {MANIFEST_VERSION}, "
            f"got {manifest.get('manifest_version')!r}"
        )
    shared = manifest.get("shared_contract")
    if not isinstance(shared, dict):
        errors.append("shared_contract required")
    else:
        for key in ("package", "version", "package_hash"):
            if not shared.get(key):
                errors.append(f"shared_contract.{key} required")
    for section in ("schemas", "vocabularies", "policies", "registries"):
        if section in manifest and not isinstance(manifest.get(section), dict):
            errors.append(f"{section} must be an object")
    return errors


def require_valid_manifest(manifest: Mapping[str, Any]) -> None:
    errors = validate_manifest_structure(manifest)
    if errors:
        raise EnvelopeValidationError(
            "Invalid authorization manifest: " + "; ".join(errors),
            errors=list(errors),
        )


def manifest_content_hash(manifest: Mapping[str, Any]) -> str:
    body = {
        k: v
        for k, v in manifest.items()
        if k
        not in (
            "manifest_hash",
            "manifest_signature",
            "signature_algorithm",
            "signed_payload_hash",
        )
    }
    return compute_hash(body)


def verify_manifest_hash(manifest: Mapping[str, Any]) -> bool:
    if "manifest_hash" not in manifest:
        return False
    return verify_hash(dict(manifest), "manifest_hash")
