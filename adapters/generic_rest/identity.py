"""Service identity model for REST modes (P1-C).

Institutional-service mode rejects static bearer-token equality as the sole
identity mechanism. Development-local may use a shared API key for loopback.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ServiceIdentity:
    caller_id: str
    tenant_id: str
    role: str
    permissions: frozenset[str]
    verified: bool


DEVELOPMENT_LOCAL = "development-local"
INSTITUTIONAL_SERVICE = "institutional-service"
VALID_MODES = frozenset({DEVELOPMENT_LOCAL, INSTITUTIONAL_SERVICE})

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "evaluator": frozenset({"evaluate", "export", "read_own_artifacts"}),
    "recorder": frozenset({"evaluate", "records", "export", "read_own_artifacts"}),
    "auditor": frozenset({"read_own_artifacts", "read_tenant_artifacts", "policy"}),
    "admin": frozenset(
        {"evaluate", "records", "export", "read_own_artifacts", "read_tenant_artifacts", "policy"}
    ),
}


def resolve_service_mode(explicit: str | None = None) -> str:
    raw = (explicit or os.environ.get("AKTA_REST_MODE") or "").strip().lower()
    if not raw:
        return DEVELOPMENT_LOCAL
    if raw in ("institutional", "institutional-service"):
        return INSTITUTIONAL_SERVICE
    if raw in ("development", "development-local", "local", "dev"):
        return DEVELOPMENT_LOCAL
    if raw not in VALID_MODES:
        raise ValueError(f"unknown AKTA REST mode: {raw}")
    return raw


def load_service_identity_registry(path: str | Path | None = None) -> dict[str, Any]:
    """Load verified service identities (public descriptors + credential digests)."""
    env_path = path or os.environ.get("AKTA_REST_IDENTITY_REGISTRY", "").strip()
    if not env_path:
        return {"version": None, "identities": {}}
    data = json.loads(Path(env_path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("identity registry must be a JSON object")
    data.setdefault("identities", {})
    return data


def _digest(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def authenticate_request(
    *,
    mode: str,
    bearer_or_key: str | None,
    api_key: str | None,
    service_tokens: frozenset[str],
    identity_registry: dict[str, Any],
    tenant_header: str | None,
) -> ServiceIdentity | None:
    """Resolve caller identity.

    Institutional mode requires a registry entry whose credential digest matches
    the presented secret AND whose tenant_id binds to X-AKTA-Tenant. Static
    equality against a shared AKTA_REST_API_KEY alone is rejected.
    """
    if mode == DEVELOPMENT_LOCAL:
        if api_key and bearer_or_key == api_key:
            return ServiceIdentity(
                caller_id="dev-local",
                tenant_id=tenant_header or "dev",
                role="admin",
                permissions=ROLE_PERMISSIONS["admin"],
                verified=False,
            )
        if bearer_or_key and bearer_or_key in service_tokens:
            return ServiceIdentity(
                caller_id="dev-token",
                tenant_id=tenant_header or "dev",
                role="evaluator",
                permissions=ROLE_PERMISSIONS["evaluator"],
                verified=False,
            )
        if not api_key and not service_tokens:
            return ServiceIdentity(
                caller_id="anonymous-loopback",
                tenant_id=tenant_header or "dev",
                role="admin",
                permissions=ROLE_PERMISSIONS["admin"],
                verified=False,
            )
        return None

    # institutional-service
    if not bearer_or_key:
        return None
    if api_key and bearer_or_key == api_key and not identity_registry.get("identities"):
        # Explicitly reject shared static bearer as institutional identity.
        return None

    digest = _digest(bearer_or_key)
    identities = identity_registry.get("identities") or {}
    for caller_id, entry in identities.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("credential_sha256") != digest:
            continue
        if entry.get("status", "active") != "active":
            return None
        tenant_id = str(entry.get("tenant_id") or "")
        if tenant_header and tenant_id and tenant_header != tenant_id:
            return None
        role = str(entry.get("role") or "evaluator")
        raw_perms = entry.get("permissions")
        if raw_perms is None:
            perms = ROLE_PERMISSIONS.get(role, frozenset())
        else:
            perms = frozenset(str(p) for p in raw_perms)
        return ServiceIdentity(
            caller_id=str(caller_id),
            tenant_id=tenant_id or (tenant_header or ""),
            role=role,
            permissions=perms,
            verified=True,
        )
    return None


def institutional_startup_errors(
    *,
    mode: str,
    identity_registry: dict[str, Any],
    artifact_store_kind: str,
    audit_ledger_kind: str,
    trusted_proxy: bool,
    policy_manifest_verified: bool,
) -> list[str]:
    if mode != INSTITUTIONAL_SERVICE:
        return []
    errors: list[str] = []
    if not (identity_registry.get("identities") or {}):
        errors.append("institutional-service requires verified identity registry")
    if artifact_store_kind != "file":
        errors.append("institutional-service requires persistent file artifact store")
    if audit_ledger_kind != "file":
        errors.append("institutional-service requires persistent file audit ledger")
    if not trusted_proxy:
        errors.append("institutional-service requires TLS-terminating trusted proxy config")
    if not policy_manifest_verified:
        errors.append("institutional-service requires policy manifest verification")
    return errors


__all__ = [
    "DEVELOPMENT_LOCAL",
    "INSTITUTIONAL_SERVICE",
    "ROLE_PERMISSIONS",
    "ServiceIdentity",
    "authenticate_request",
    "institutional_startup_errors",
    "load_service_identity_registry",
    "resolve_service_mode",
]
