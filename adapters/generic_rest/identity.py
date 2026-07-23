"""Service identity model for REST modes (P1-C / WS13).

Modes:
- ``development-local``: loopback-friendly; optional API key
- ``pilot-service``: static credential-digest registry (non-institutional)
- ``institutional-service``: OIDC issuer + audience verification

Institutional mode rejects static bearer-token equality and pilot registry
digests as the sole identity mechanism.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEVELOPMENT_LOCAL = "development-local"
PILOT_SERVICE = "pilot-service"
INSTITUTIONAL_SERVICE = "institutional-service"
# Back-compat alias used in older docs/tests for the digest-registry path.
STATIC_REGISTRY = PILOT_SERVICE
VALID_MODES = frozenset({DEVELOPMENT_LOCAL, PILOT_SERVICE, INSTITUTIONAL_SERVICE})

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "evaluator": frozenset({"evaluate", "export", "read_own_artifacts"}),
    "recorder": frozenset({"evaluate", "records", "export", "read_own_artifacts"}),
    "auditor": frozenset({"read_own_artifacts", "read_tenant_artifacts", "policy"}),
    "admin": frozenset(
        {"evaluate", "records", "export", "read_own_artifacts", "read_tenant_artifacts", "policy"}
    ),
}


@dataclass(frozen=True)
class ServiceIdentity:
    caller_id: str
    tenant_id: str
    role: str
    permissions: frozenset[str]
    verified: bool
    auth_method: str = "unknown"
    token_claims: tuple[tuple[str, str], ...] = ()


def resolve_service_mode(explicit: str | None = None) -> str:
    raw = (explicit or os.environ.get("AKTA_REST_MODE") or "").strip().lower()
    if not raw:
        return DEVELOPMENT_LOCAL
    aliases = {
        "institutional": INSTITUTIONAL_SERVICE,
        "institutional-service": INSTITUTIONAL_SERVICE,
        "pilot": PILOT_SERVICE,
        "pilot-service": PILOT_SERVICE,
        # Former name for the digest-registry path.
        "static-registry": PILOT_SERVICE,
        "static_registry": PILOT_SERVICE,
        "development": DEVELOPMENT_LOCAL,
        "development-local": DEVELOPMENT_LOCAL,
        "local": DEVELOPMENT_LOCAL,
        "dev": DEVELOPMENT_LOCAL,
    }
    if raw in aliases:
        return aliases[raw]
    if raw not in VALID_MODES:
        raise ValueError(f"unknown AKTA REST mode: {raw}")
    return raw


def load_service_identity_registry(path: str | Path | None = None) -> dict[str, Any]:
    """Load verified service identities (public descriptors + credential digests).

    Used by ``pilot-service`` only. Institutional mode uses OIDC.
    """
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


def _oidc_settings() -> dict[str, str]:
    return {
        "issuer": os.environ.get("AKTA_OIDC_ISSUER", "").strip(),
        "audience": os.environ.get("AKTA_OIDC_AUDIENCE", "").strip(),
        "jwks_url": os.environ.get("AKTA_OIDC_JWKS_URL", "").strip(),
        "tenant_claim": os.environ.get("AKTA_OIDC_TENANT_CLAIM", "tenant_id").strip()
        or "tenant_id",
        "role_claim": os.environ.get("AKTA_OIDC_ROLE_CLAIM", "role").strip() or "role",
        "subject_claim": os.environ.get("AKTA_OIDC_SUBJECT_CLAIM", "sub").strip() or "sub",
    }


def verify_oidc_bearer(
    token: str,
    *,
    issuer: str | None = None,
    audience: str | None = None,
    jwks_url: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Verify an OIDC access/ID token (issuer + audience).

    Requires optional dependency ``PyJWT`` (and ``cryptography`` for RS*/ES*).
    Set ``AKTA_OIDC_JWKS_URL`` or pass ``jwks_url`` for signature verification.
    """
    settings = _oidc_settings()
    iss = (issuer or settings["issuer"]).strip()
    aud = (audience or settings["audience"]).strip()
    jwks = (jwks_url or settings["jwks_url"]).strip()
    if not iss or not aud:
        raise ValueError("institutional OIDC requires AKTA_OIDC_ISSUER and AKTA_OIDC_AUDIENCE")

    try:
        import jwt
        from jwt import PyJWKClient
    except ImportError as exc:
        raise ImportError(
            "institutional OIDC requires PyJWT. Install with: "
            "pip install 'akta-protocol[rest]'  (or pip install PyJWT)"
        ) from exc

    options = {
        "require": ["exp", "iat", "iss", "aud", "sub"],
        "verify_aud": True,
        "verify_iss": True,
    }
    decode_kwargs: dict[str, Any] = {
        "algorithms": ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EdDSA"],
        "audience": aud,
        "issuer": iss,
        "options": options,
        "leeway": 30,
    }
    if jwks:
        client = PyJWKClient(jwks, cache_keys=True)
        signing_key = client.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, signing_key.key, **decode_kwargs)
    else:
        # Explicit insecure escape hatch for offline unit tests only.
        if os.environ.get("AKTA_OIDC_ALLOW_UNVERIFIED", "").strip().lower() not in (
            "1",
            "true",
            "yes",
        ):
            raise ValueError(
                "institutional OIDC requires AKTA_OIDC_JWKS_URL "
                "(or AKTA_OIDC_ALLOW_UNVERIFIED=1 for offline tests only)"
            )
        claims = jwt.decode(
            token,
            options={**options, "verify_signature": False},
            audience=aud,
            issuer=iss,
            leeway=30,
        )

    # Defense-in-depth clock check even when library already verified exp.
    ts = now if now is not None else time.time()
    exp = claims.get("exp")
    if exp is not None and float(exp) < ts - 30:
        raise ValueError("OIDC token expired")
    return dict(claims)


def authenticate_oidc_request(
    *,
    bearer_token: str | None,
    tenant_header: str | None,
    oidc_claims: dict[str, Any] | None = None,
) -> ServiceIdentity | None:
    """Resolve institutional identity from a verified OIDC token."""
    if not bearer_token and oidc_claims is None:
        return None
    try:
        claims = oidc_claims if oidc_claims is not None else verify_oidc_bearer(bearer_token or "")
    except Exception:
        return None

    settings = _oidc_settings()
    caller_id = str(claims.get(settings["subject_claim"]) or claims.get("sub") or "").strip()
    if not caller_id:
        return None
    tenant_id = str(
        claims.get(settings["tenant_claim"])
        or claims.get("tenant")
        or claims.get("org_id")
        or ""
    ).strip()
    if tenant_header and tenant_id and tenant_header != tenant_id:
        return None
    if tenant_header and not tenant_id:
        tenant_id = tenant_header
    if not tenant_id:
        return None
    role = str(claims.get(settings["role_claim"]) or claims.get("akta_role") or "evaluator")
    raw_perms = claims.get("permissions") or claims.get("akta_permissions")
    if raw_perms is None:
        perms = ROLE_PERMISSIONS.get(role, frozenset())
    else:
        perms = frozenset(str(p) for p in raw_perms)
    claim_pairs = tuple(
        (str(k), str(v))
        for k, v in sorted(claims.items())
        if k in {"iss", "aud", "sub", settings["tenant_claim"], settings["role_claim"]}
    )
    return ServiceIdentity(
        caller_id=caller_id,
        tenant_id=tenant_id,
        role=role,
        permissions=perms,
        verified=True,
        auth_method="oidc",
        token_claims=claim_pairs,
    )


def authenticate_request(
    *,
    mode: str,
    bearer_or_key: str | None,
    api_key: str | None,
    service_tokens: frozenset[str],
    identity_registry: dict[str, Any],
    tenant_header: str | None,
    oidc_claims: dict[str, Any] | None = None,
) -> ServiceIdentity | None:
    """Resolve caller identity for the active REST mode."""
    if mode == DEVELOPMENT_LOCAL:
        if api_key and bearer_or_key == api_key:
            return ServiceIdentity(
                caller_id="dev-local",
                tenant_id=tenant_header or "dev",
                role="admin",
                permissions=ROLE_PERMISSIONS["admin"],
                verified=False,
                auth_method="dev_api_key",
            )
        if bearer_or_key and bearer_or_key in service_tokens:
            return ServiceIdentity(
                caller_id="dev-token",
                tenant_id=tenant_header or "dev",
                role="evaluator",
                permissions=ROLE_PERMISSIONS["evaluator"],
                verified=False,
                auth_method="dev_token",
            )
        if not api_key and not service_tokens:
            return ServiceIdentity(
                caller_id="anonymous-loopback",
                tenant_id=tenant_header or "dev",
                role="admin",
                permissions=ROLE_PERMISSIONS["admin"],
                verified=False,
                auth_method="anonymous_loopback",
            )
        return None

    if mode == INSTITUTIONAL_SERVICE:
        # Reject shared static API key equality as institutional identity.
        if api_key and bearer_or_key == api_key:
            return None
        return authenticate_oidc_request(
            bearer_token=bearer_or_key,
            tenant_header=tenant_header,
            oidc_claims=oidc_claims,
        )

    # pilot-service (formerly static-registry / institutional digest path)
    if not bearer_or_key:
        return None
    if api_key and bearer_or_key == api_key and not identity_registry.get("identities"):
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
            auth_method="pilot_registry",
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
    oidc_configured: bool | None = None,
) -> list[str]:
    if mode == PILOT_SERVICE:
        errors: list[str] = []
        if not (identity_registry.get("identities") or {}):
            errors.append("pilot-service requires verified identity registry")
        if artifact_store_kind not in {"file", "sqlite"}:
            errors.append("pilot-service requires persistent file or sqlite artifact store")
        if audit_ledger_kind not in {"file", "sqlite"}:
            errors.append("pilot-service requires persistent file or sqlite audit ledger")
        return errors

    if mode != INSTITUTIONAL_SERVICE:
        return []

    errors = []
    settings = _oidc_settings()
    oidc_ok = (
        oidc_configured
        if oidc_configured is not None
        else bool(settings["issuer"] and settings["audience"])
    )
    if not oidc_ok:
        errors.append(
            "institutional-service requires OIDC issuer+audience "
            "(AKTA_OIDC_ISSUER, AKTA_OIDC_AUDIENCE)"
        )
    if artifact_store_kind != "postgresql":
        errors.append("institutional-service requires PostgreSQL artifact store")
    if audit_ledger_kind != "postgresql":
        errors.append("institutional-service requires PostgreSQL audit ledger")
    if not trusted_proxy:
        errors.append("institutional-service requires TLS-terminating trusted proxy config")
    if not policy_manifest_verified:
        errors.append("institutional-service requires policy manifest verification")
    return errors


__all__ = [
    "DEVELOPMENT_LOCAL",
    "INSTITUTIONAL_SERVICE",
    "PILOT_SERVICE",
    "ROLE_PERMISSIONS",
    "STATIC_REGISTRY",
    "ServiceIdentity",
    "authenticate_oidc_request",
    "authenticate_request",
    "institutional_startup_errors",
    "load_service_identity_registry",
    "resolve_service_mode",
    "verify_oidc_bearer",
]
