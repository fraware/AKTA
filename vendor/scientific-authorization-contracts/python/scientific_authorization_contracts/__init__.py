"""Loader for scientific-authorization-contracts (shared SCOPE/AKTA schemas)."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ENVELOPE_VERSION = "scientific-authorization-envelope-v2"
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = PACKAGE_ROOT / "schemas"
VOCAB_DIR = PACKAGE_ROOT / "vocabularies"
CONFORMANCE_DIR = PACKAGE_ROOT / "conformance"


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def capability_families() -> frozenset[str]:
    data = _load_json(VOCAB_DIR / "capability_families.json")
    return frozenset(data["families"])


@lru_cache(maxsize=1)
def family_operations() -> dict[str, list[str]]:
    data = _load_json(VOCAB_DIR / "operations.json")
    return {family: list(spec["order"]) for family, spec in data["families"].items()}


@lru_cache(maxsize=1)
def responsibility_rank() -> dict[str, int]:
    data = _load_json(VOCAB_DIR / "responsibility_levels.json")
    return {item["id"]: int(item["rank"]) for item in data["levels"]}


@lru_cache(maxsize=1)
def expiration_events() -> frozenset[str]:
    data = _load_json(VOCAB_DIR / "expiration_events.json")
    return frozenset(data["events"])


@lru_cache(maxsize=1)
def legacy_scope_migration() -> dict[str, tuple[str, str]]:
    data = _load_json(VOCAB_DIR / "legacy_scope_migration.json")
    return {
        name: (str(spec["family"]), str(spec["operation"]))
        for name, spec in data["mappings"].items()
    }


@lru_cache(maxsize=1)
def target_types() -> frozenset[str]:
    data = _load_json(VOCAB_DIR / "target_types.json")
    return frozenset(data["types"])


@lru_cache(maxsize=1)
def constraint_types() -> dict[str, dict[str, Any]]:
    data = _load_json(VOCAB_DIR / "constraint_types.json")
    return dict(data["types"])


def load_schema(name: str) -> dict[str, Any]:
    path = SCHEMAS_DIR / name
    return _load_json(path)


@lru_cache(maxsize=8)
def schema_file_hash(name: str) -> str:
    """SHA-256 of the raw schema file bytes (canonical shared artifact hash)."""
    path = SCHEMAS_DIR / name
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def authorization_envelope_schema_hash() -> str:
    return schema_file_hash("authorization_envelope.v2.schema.json")


def authorization_schema_provenance() -> dict[str, str]:
    return {
        "authorization_schema_version": ENVELOPE_VERSION,
        "authorization_schema_hash": authorization_envelope_schema_hash(),
    }


def grant_schema_version() -> str:
    return "scope-grant-v2"


def grant_schema_hash() -> str:
    return schema_file_hash("scope_grant.v2.schema.json")


def load_conformance_cases(kind: str) -> list[dict[str, Any]]:
    root = CONFORMANCE_DIR / kind
    if not root.is_dir():
        return []
    cases: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        cases.append(_load_json(path))
    return cases


# Re-export envelope API for consumers.
from scientific_authorization_contracts.envelope import (  # noqa: E402
    AuthorizationEnvelope,
    EnvelopeConflictError,
    EnvelopeValidationError,
    compare_envelopes,
    envelope_contains,
    envelope_covers,
    envelope_from_legacy_scope,
    envelope_is_narrower,
    load_envelope_schema,
    new_capability_id,
    validate_envelope_dict,
)
from scientific_authorization_contracts.hashing import (  # noqa: E402
    attach_hash,
    compute_hash,
    verify_hash,
)

__all__ = [
    "ENVELOPE_VERSION",
    "AuthorizationEnvelope",
    "EnvelopeConflictError",
    "EnvelopeValidationError",
    "attach_hash",
    "authorization_envelope_schema_hash",
    "authorization_schema_provenance",
    "capability_families",
    "compare_envelopes",
    "compute_hash",
    "constraint_types",
    "envelope_contains",
    "envelope_covers",
    "envelope_from_legacy_scope",
    "envelope_is_narrower",
    "expiration_events",
    "family_operations",
    "grant_schema_hash",
    "grant_schema_version",
    "legacy_scope_migration",
    "load_conformance_cases",
    "load_envelope_schema",
    "load_schema",
    "new_capability_id",
    "responsibility_rank",
    "schema_file_hash",
    "target_types",
    "validate_envelope_dict",
    "verify_hash",
]
