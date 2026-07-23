"""Resolve and load the installed scientific-authorization-contracts package.

Runtime imports the installed distribution only. Install from the vendor tree:

    pip install ./vendor/scientific-authorization-contracts

before AKTA editable or wheel installs. Vendor/sibling ``sys.path`` injection
is intentionally not used.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

ENVELOPE_VERSION = "scientific-authorization-envelope-v2"
ENVELOPE_SCHEMA_NAME = "authorization_envelope.v2.schema.json"
GRANT_V2_SCHEMA_NAME = "scope_grant.v2.schema.json"
GRANT_STATUS_SCHEMA_NAME = "scope_grant_status.v1.schema.json"
CONTRACTS_PACKAGE_NAME = "scientific-authorization-contracts"
CONTRACTS_PACKAGE_VERSION = "2.1.0"


@lru_cache(maxsize=1)
def _contracts():
    try:
        import scientific_authorization_contracts as contracts
    except ImportError as exc:
        raise ImportError(
            "scientific-authorization-contracts is not installed. "
            "Install from the vendor tree before using AKTA: "
            "pip install ./vendor/scientific-authorization-contracts"
        ) from exc
    version = getattr(contracts, "__version__", None) or getattr(
        contracts, "PACKAGE_VERSION", None
    )
    if version and str(version) != CONTRACTS_PACKAGE_VERSION:
        raise ImportError(
            f"scientific-authorization-contracts {version!r} loaded; "
            f"AKTA requires {CONTRACTS_PACKAGE_VERSION!r}"
        )
    return contracts


def contracts_package_version() -> str:
    return str(getattr(_contracts(), "__version__", CONTRACTS_PACKAGE_VERSION))


def release_artifact_hash() -> str:
    c = _contracts()
    if hasattr(c, "release_artifact_hash"):
        return str(c.release_artifact_hash())
    # Older/sibling installs may omit the helper; fall back to package metadata hash.
    version = str(getattr(c, "__version__", None) or getattr(c, "PACKAGE_VERSION", "") or "")
    try:
        from akta.hash import hash_object

        return hash_object(
            {
                "package": CONTRACTS_PACKAGE_NAME,
                "package_version": version or CONTRACTS_PACKAGE_VERSION,
                "envelope_schema_hash": str(c.authorization_envelope_schema_hash()),
                "grant_schema_hash": str(c.grant_schema_hash()),
            }
        )
    except Exception as exc:  # noqa: BLE001
        raise AttributeError(
            "installed contracts package lacks release_artifact_hash()"
        ) from exc


def envelope_version() -> str:
    return str(_contracts().ENVELOPE_VERSION)


def authorization_envelope_schema_hash() -> str:
    return str(_contracts().authorization_envelope_schema_hash())


def authorization_schema_provenance() -> dict[str, str]:
    return dict(_contracts().authorization_schema_provenance())


def capability_families() -> frozenset[str]:
    return _contracts().capability_families()


def family_operations() -> dict[str, list[str]]:
    return _contracts().family_operations()


def responsibility_rank() -> dict[str, int]:
    return _contracts().responsibility_rank()


def legacy_scope_migration() -> dict[str, tuple[str, str]]:
    return _contracts().legacy_scope_migration()


def grant_schema_version() -> str:
    return str(_contracts().grant_schema_version())


def grant_schema_hash() -> str:
    return str(_contracts().grant_schema_hash())


def load_contract_schema(name: str) -> dict[str, Any]:
    return _contracts().load_schema(name)


def load_conformance_cases(kind: str) -> list[dict[str, Any]]:
    return list(_contracts().load_conformance_cases(kind))


def operation_vocabulary() -> str:
    return ",".join(sorted(family_operations().keys()))


def shared_contract_report() -> dict[str, str]:
    """Acceptance report fields for AKTA ↔ SCOPE schema identity."""
    c = _contracts()
    report = {
        "package": CONTRACTS_PACKAGE_NAME,
        "package_version": contracts_package_version(),
        "envelope_schema_version": str(c.ENVELOPE_VERSION),
        "envelope_schema_hash": str(c.authorization_envelope_schema_hash()),
        "grant_schema_version": str(c.grant_schema_version()),
        "grant_schema_hash": str(c.grant_schema_hash()),
        "family_vocabulary": ",".join(sorted(c.capability_families())),
        "operation_vocabulary": ",".join(sorted(c.family_operations().keys())),
        "release_artifact_hash": release_artifact_hash(),
    }
    return report
