"""Resolve and load scientific-authorization-contracts (shared SCOPE/AKTA).

Preference order:
1. Installed ``scientific_authorization_contracts`` distribution
2. Sibling SCOPE repo ``scientific-authorization-contracts``
3. Vendored copy under ``vendor/scientific-authorization-contracts``
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

_AKTA_ROOT = Path(__file__).resolve().parent.parent
_VENDOR_CONTRACTS = _AKTA_ROOT / "vendor" / "scientific-authorization-contracts"
_VENDOR_PYTHON = _VENDOR_CONTRACTS / "python"

ENVELOPE_VERSION = "scientific-authorization-envelope-v2"
ENVELOPE_SCHEMA_NAME = "authorization_envelope.v2.schema.json"
GRANT_V2_SCHEMA_NAME = "scope_grant.v2.schema.json"
GRANT_STATUS_SCHEMA_NAME = "scope_grant_status.v1.schema.json"


def _sibling_contracts_root() -> Path | None:
    scope_repo = os.environ.get("SCOPE_REPO_PATH", "").strip()
    candidates: list[Path] = []
    if scope_repo:
        candidates.append(Path(scope_repo) / "scientific-authorization-contracts")
    parent = _AKTA_ROOT.parent
    candidates.append(parent / "SCOPE" / "scientific-authorization-contracts")
    for path in candidates:
        if (path / "schemas" / ENVELOPE_SCHEMA_NAME).is_file():
            return path.resolve()
    return None


def contracts_root() -> Path:
    """Prefer vendored contracts (with comparison API); fall back to sibling SCOPE."""
    if (_VENDOR_CONTRACTS / "schemas" / ENVELOPE_SCHEMA_NAME).is_file():
        # Prefer vendor when it has the comparison module (envelope.py).
        vendor_envelope = (
            _VENDOR_PYTHON / "scientific_authorization_contracts" / "envelope.py"
        )
        if vendor_envelope.is_file():
            return _VENDOR_CONTRACTS.resolve()
    sibling = _sibling_contracts_root()
    if sibling is not None:
        return sibling
    if (_VENDOR_CONTRACTS / "schemas" / ENVELOPE_SCHEMA_NAME).is_file():
        return _VENDOR_CONTRACTS.resolve()
    raise FileNotFoundError(
        "scientific-authorization-contracts not found (sibling SCOPE or vendor/)"
    )


def _ensure_import_path() -> Path:
    root = contracts_root()
    python_path = root / "python"
    path_str = str(python_path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
    return python_path


@lru_cache(maxsize=1)
def _contracts():
    _ensure_import_path()
    import scientific_authorization_contracts as contracts

    return contracts


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
    return {
        "envelope_schema_version": str(c.ENVELOPE_VERSION),
        "envelope_schema_hash": str(c.authorization_envelope_schema_hash()),
        "grant_schema_version": str(c.grant_schema_version()),
        "grant_schema_hash": str(c.grant_schema_hash()),
        "family_vocabulary": ",".join(sorted(c.capability_families())),
        "operation_vocabulary": ",".join(sorted(c.family_operations().keys())),
        "contracts_root": str(contracts_root()),
    }
