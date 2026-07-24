"""Vocabulary and schema loaders (no algebra imports — breaks cycles)."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from importlib import metadata
from pathlib import Path
from typing import Any

ENVELOPE_VERSION = "scientific-authorization-envelope-v2"
PACKAGE_VERSION = "2.2.0"
PACKAGE_ROOT = Path(__file__).resolve().parent
SCHEMAS_DIR = PACKAGE_ROOT / "schemas"
VOCAB_DIR = PACKAGE_ROOT / "vocabularies"
CONFORMANCE_DIR = PACKAGE_ROOT / "conformance"


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def package_version() -> str:
    try:
        return metadata.version("scientific-authorization-contracts")
    except metadata.PackageNotFoundError:
        return PACKAGE_VERSION


@lru_cache(maxsize=1)
def capability_families() -> frozenset[str]:
    data = _load_json(VOCAB_DIR / "capability_families.json")
    return frozenset(data["families"])


@lru_cache(maxsize=1)
def family_operations() -> dict[str, list[str]]:
    data = _load_json(VOCAB_DIR / "operations.json")
    result: dict[str, list[str]] = {}
    for family, spec in data["families"].items():
        if "operations" in spec:
            result[family] = list(spec["operations"])
        elif "order" in spec:
            # Legacy total-order arrays (pre-2.2) — treat as declaration order only.
            result[family] = list(spec["order"])
        else:
            result[family] = sorted(spec.get("covers", {}).keys())
    return result


@lru_cache(maxsize=1)
def family_covers() -> dict[str, dict[str, list[str]]]:
    """Per-family covers adjacency: op -> list of directly covered (less privileged) ops."""
    data = _load_json(VOCAB_DIR / "operations.json")
    result: dict[str, dict[str, list[str]]] = {}
    for family, spec in data["families"].items():
        if "covers" in spec:
            result[family] = {
                str(op): [str(c) for c in children]
                for op, children in spec["covers"].items()
            }
            continue
        # Migrate legacy total-order arrays to a linear covers chain.
        order = list(spec.get("order") or [])
        covers: dict[str, list[str]] = {}
        for idx, op in enumerate(order):
            covers[str(op)] = [str(order[idx - 1])] if idx > 0 else []
        result[family] = covers
    return result


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
    path = SCHEMAS_DIR / name
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def vocabulary_file_hash(name: str) -> str:
    path = VOCAB_DIR / name
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def authorization_envelope_schema_hash() -> str:
    return schema_file_hash("authorization_envelope.v2.schema.json")


def contracts_package_content_hash() -> str:
    """Deterministic release hash over schemas + vocabularies (wheel-stable)."""
    digest = hashlib.sha256()
    for root in (SCHEMAS_DIR, VOCAB_DIR):
        if not root.is_dir():
            continue
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = path.relative_to(PACKAGE_ROOT).as_posix().encode("utf-8")
            digest.update(rel)
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def runtime_evaluator_registry_hash() -> str:
    """Hash of declared constraint types bound to runtime evaluators."""
    from scientific_authorization_contracts.constraints import constraint_registry
    from scientific_authorization_contracts.hashing import compute_hash

    registry = constraint_registry()
    payload = {
        "constraint_types": sorted(registry.keys()),
        "vocabulary": constraint_types(),
    }
    return compute_hash(payload)


def authorization_schema_provenance() -> dict[str, str]:
    return {
        "authorization_schema_version": ENVELOPE_VERSION,
        "authorization_schema_hash": authorization_envelope_schema_hash(),
        "contracts_package_version": package_version(),
        "contracts_package_hash": contracts_package_content_hash(),
        "grant_schema_hash": grant_schema_hash(),
        "grant_status_schema_hash": schema_file_hash("scope_grant_status.v1.schema.json"),
        "capability_families_vocab_hash": vocabulary_file_hash("capability_families.json"),
        "operations_vocab_hash": vocabulary_file_hash("operations.json"),
        "constraint_types_vocab_hash": vocabulary_file_hash("constraint_types.json"),
        "target_types_vocab_hash": vocabulary_file_hash("target_types.json"),
        "expiration_events_vocab_hash": vocabulary_file_hash("expiration_events.json"),
        "runtime_evaluator_registry_hash": runtime_evaluator_registry_hash(),
    }


GRANT_PROFILE_DEVELOPMENT = "scope-grant-development-v2"
GRANT_PROFILE_INSTITUTIONAL = "scope-grant-institutional-v2"


def grant_schema_version() -> str:
    return "scope-grant-v2"


def grant_schema_hash() -> str:
    return schema_file_hash("scope_grant.v2.schema.json")


def grant_profile_schema_name(profile: str) -> str:
    """Return schema filename for a grant profile id or short alias."""
    aliases = {
        "development": GRANT_PROFILE_DEVELOPMENT,
        "institutional": GRANT_PROFILE_INSTITUTIONAL,
        GRANT_PROFILE_DEVELOPMENT: GRANT_PROFILE_DEVELOPMENT,
        GRANT_PROFILE_INSTITUTIONAL: GRANT_PROFILE_INSTITUTIONAL,
    }
    resolved = aliases.get(profile)
    if resolved is None:
        raise ValueError(f"Unknown grant schema profile: {profile!r}")
    return f"{resolved}.schema.json"


def load_grant_profile_schema(profile: str = "development") -> dict[str, Any]:
    return load_schema(grant_profile_schema_name(profile))


def grant_profile_schema_hash(profile: str = "institutional") -> str:
    return schema_file_hash(grant_profile_schema_name(profile))


def load_conformance_cases(kind: str) -> list[dict[str, Any]]:
    root = CONFORMANCE_DIR / kind
    if not root.is_dir():
        return []
    cases: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        cases.append(_load_json(path))
    return cases


def contracts_root() -> Path:
    return PACKAGE_ROOT


@lru_cache(maxsize=1)
def contracts_schema_registry():
    """
    Registry-based JSON Schema resolution over installed contract schemas.

    Resolves ``$ref`` values by schema filename and by ``$id`` URI so
    institutional grant composition (envelope / manifest / status) validates
    against the wheel-installed schemas without rewriting refs to plain objects.
    """
    from referencing import Registry, Resource

    registry: Registry = Registry()
    if not SCHEMAS_DIR.is_dir():
        return registry
    for path in sorted(SCHEMAS_DIR.glob("*.json")):
        contents = _load_json(path)
        resource = Resource.from_contents(contents)
        registry = registry.with_resource(path.name, resource)
        schema_id = contents.get("$id")
        if schema_id:
            registry = registry.with_resource(str(schema_id), resource)
    return registry


def validate_against_schema(
    instance: dict[str, Any],
    schema_name: str,
) -> None:
    """Validate ``instance`` against an installed contracts schema (fail closed)."""
    import jsonschema

    schema = load_schema(schema_name)
    validator = jsonschema.Draft202012Validator(
        schema, registry=contracts_schema_registry()
    )
    validator.validate(instance)
