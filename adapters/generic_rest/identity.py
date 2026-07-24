"""Service identity model for REST modes (P1-C / WS13 / P1-14).

Modes:
- ``development-local``: loopback-friendly; optional API key
- ``pilot-service``: static credential-digest registry (non-institutional)
- ``institutional-service``: OIDC issuer + audience + signature verification

Institutional mode rejects static bearer-token equality and pilot registry
digests as the sole identity mechanism. Signature verification cannot be
disabled via environment variables; tests may inject ``allow_unverified``
only through explicit dependency injection.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

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

_SUPPORTED_OIDC_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EdDSA"}
)
_UNVERIFIED_ENV = "AKTA_OIDC_ALLOW_UNVERIFIED"


@dataclass(frozen=True)
class ServiceIdentity:
    caller_id: str
    tenant_id: str
    role: str
    permissions: frozenset[str]
    verified: bool
    auth_method: str = "unknown"
    token_claims: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class OidcSettings:
    """Resolved institutional OIDC configuration (env + optional overrides)."""

    issuer: str
    audience: str
    jwks_url: str
    public_key: str
    algorithms: tuple[str, ...]
    tenant_claim: str
    role_claim: str
    subject_claim: str
    role_map: Mapping[str, str]


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


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def _parse_algorithms(raw: str) -> tuple[str, ...]:
    algs = tuple(a.strip() for a in raw.split(",") if a.strip())
    unknown = [a for a in algs if a not in _SUPPORTED_OIDC_ALGORITHMS]
    if unknown:
        raise ValueError(
            "unsupported OIDC algorithm(s): "
            + ", ".join(unknown)
            + f"; allowed: {', '.join(sorted(_SUPPORTED_OIDC_ALGORITHMS))}"
        )
    return algs


def _load_public_key_material() -> str:
    path = os.environ.get("AKTA_OIDC_PUBLIC_KEY_FILE", "").strip()
    if path:
        return Path(path).read_text(encoding="utf-8").strip()
    inline = os.environ.get("AKTA_OIDC_PUBLIC_KEY", "").strip()
    if not inline:
        return ""
    return inline.replace("\\n", "\n").strip()


def _load_role_map() -> dict[str, str]:
    """Load claim-value → local AKTA role policy.

    Accepts inline JSON via ``AKTA_OIDC_ROLE_MAP`` or a file via
    ``AKTA_OIDC_ROLE_MAP_FILE``. Values must be keys of ``ROLE_PERMISSIONS``.
    """
    path = os.environ.get("AKTA_OIDC_ROLE_MAP_FILE", "").strip()
    raw = os.environ.get("AKTA_OIDC_ROLE_MAP", "").strip()
    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    elif raw:
        data = json.loads(raw)
    else:
        return {}
    if not isinstance(data, dict):
        raise ValueError("AKTA_OIDC_ROLE_MAP must be a JSON object")
    out: dict[str, str] = {}
    for claim_value, local_role in data.items():
        role = str(local_role).strip()
        if role not in ROLE_PERMISSIONS:
            raise ValueError(
                f"OIDC role map maps {str(claim_value)!r} to unknown local role {role!r}"
            )
        out[str(claim_value)] = role
    return out


def load_oidc_settings(
    *,
    issuer: str | None = None,
    audience: str | None = None,
    jwks_url: str | None = None,
    public_key: str | None = None,
    algorithms: tuple[str, ...] | list[str] | None = None,
    tenant_claim: str | None = None,
    role_claim: str | None = None,
    subject_claim: str | None = None,
    role_map: Mapping[str, str] | None = None,
) -> OidcSettings:
    """Resolve OIDC settings from explicit overrides and environment."""
    algs_env = os.environ.get("AKTA_OIDC_ALGORITHMS", "").strip()
    if algorithms is not None:
        resolved_algs = tuple(algorithms)
        unknown = [a for a in resolved_algs if a not in _SUPPORTED_OIDC_ALGORITHMS]
        if unknown:
            raise ValueError(
                "unsupported OIDC algorithm(s): "
                + ", ".join(unknown)
                + f"; allowed: {', '.join(sorted(_SUPPORTED_OIDC_ALGORITHMS))}"
            )
    elif algs_env:
        resolved_algs = _parse_algorithms(algs_env)
    else:
        resolved_algs = ()

    resolved_map: Mapping[str, str]
    if role_map is not None:
        resolved_map = dict(role_map)
        for claim_value, local_role in resolved_map.items():
            if str(local_role) not in ROLE_PERMISSIONS:
                raise ValueError(
                    f"OIDC role map maps {str(claim_value)!r} to unknown local "
                    f"role {str(local_role)!r}"
                )
    else:
        resolved_map = _load_role_map()

    return OidcSettings(
        issuer=(issuer if issuer is not None else os.environ.get("AKTA_OIDC_ISSUER", "")).strip(),
        audience=(
            audience if audience is not None else os.environ.get("AKTA_OIDC_AUDIENCE", "")
        ).strip(),
        jwks_url=(
            jwks_url if jwks_url is not None else os.environ.get("AKTA_OIDC_JWKS_URL", "")
        ).strip(),
        public_key=(
            public_key if public_key is not None else _load_public_key_material()
        ).strip(),
        algorithms=resolved_algs,
        tenant_claim=(
            tenant_claim
            if tenant_claim is not None
            else os.environ.get("AKTA_OIDC_TENANT_CLAIM", "")
        ).strip(),
        role_claim=(
            role_claim if role_claim is not None else os.environ.get("AKTA_OIDC_ROLE_CLAIM", "")
        ).strip(),
        subject_claim=(
            subject_claim
            if subject_claim is not None
            else os.environ.get("AKTA_OIDC_SUBJECT_CLAIM", "sub").strip() or "sub"
        ).strip()
        or "sub",
        role_map=resolved_map,
    )


def institutional_oidc_config_errors(settings: OidcSettings | None = None) -> list[str]:
    """Return institutional OIDC configuration errors (empty if ready)."""
    errors: list[str] = []
    if _truthy_env(_UNVERIFIED_ENV):
        errors.append(
            "institutional-service forbids AKTA_OIDC_ALLOW_UNVERIFIED "
            "(signature verification cannot be disabled via environment)"
        )

    try:
        cfg = settings if settings is not None else load_oidc_settings()
    except ValueError as exc:
        errors.append(str(exc))
        return errors

    if not cfg.issuer:
        errors.append("institutional-service requires AKTA_OIDC_ISSUER")
    if not cfg.audience:
        errors.append("institutional-service requires AKTA_OIDC_AUDIENCE")
    if not cfg.jwks_url and not cfg.public_key:
        errors.append(
            "institutional-service requires AKTA_OIDC_JWKS_URL or "
            "AKTA_OIDC_PUBLIC_KEY / AKTA_OIDC_PUBLIC_KEY_FILE"
        )
    if not cfg.algorithms:
        errors.append("institutional-service requires AKTA_OIDC_ALGORITHMS")
    if not cfg.tenant_claim:
        errors.append("institutional-service requires AKTA_OIDC_TENANT_CLAIM")
    if not cfg.role_claim:
        errors.append("institutional-service requires AKTA_OIDC_ROLE_CLAIM")
    if not cfg.role_map:
        errors.append(
            "institutional-service requires AKTA_OIDC_ROLE_MAP or "
            "AKTA_OIDC_ROLE_MAP_FILE (local claim-to-role policy)"
        )
    return errors


def oidc_institutional_ready(settings: OidcSettings | None = None) -> bool:
    return not institutional_oidc_config_errors(settings)


def verify_oidc_bearer(
    token: str,
    *,
    issuer: str | None = None,
    audience: str | None = None,
    jwks_url: str | None = None,
    public_key: str | None = None,
    algorithms: tuple[str, ...] | list[str] | None = None,
    now: float | None = None,
    allow_unverified: bool = False,
) -> dict[str, Any]:
    """Verify an OIDC access/ID token (issuer + audience + signature).

    Requires optional dependency ``PyJWT`` (and ``cryptography`` for RS*/ES*).

    Signature verification uses ``jwks_url`` or a pinned ``public_key``.
    ``allow_unverified=True`` is a **test-only** dependency-injection escape
    hatch; this function never enables unverified mode from environment
    variables (``AKTA_OIDC_ALLOW_UNVERIFIED`` is rejected at institutional
    startup instead).
    """
    settings = load_oidc_settings(
        issuer=issuer,
        audience=audience,
        jwks_url=jwks_url,
        public_key=public_key,
        algorithms=algorithms,
    )
    iss = settings.issuer
    aud = settings.audience
    jwks = settings.jwks_url
    key_pem = settings.public_key
    algs = list(settings.algorithms)
    if not iss or not aud:
        raise ValueError("institutional OIDC requires AKTA_OIDC_ISSUER and AKTA_OIDC_AUDIENCE")
    if not algs:
        raise ValueError("institutional OIDC requires AKTA_OIDC_ALGORITHMS")

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
        "algorithms": algs,
        "audience": aud,
        "issuer": iss,
        "options": options,
        "leeway": 30,
    }

    if jwks:
        client = PyJWKClient(jwks, cache_keys=True)
        signing_key = client.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, signing_key.key, **decode_kwargs)
    elif key_pem:
        claims = jwt.decode(token, key_pem, **decode_kwargs)
    elif allow_unverified:
        # Test-only DI path: never gated by environment in production code.
        claims = jwt.decode(
            token,
            options={**options, "verify_signature": False},
            algorithms=algs,
            audience=aud,
            issuer=iss,
            leeway=30,
        )
    else:
        raise ValueError(
            "institutional OIDC requires AKTA_OIDC_JWKS_URL or a pinned public "
            "verification key (AKTA_OIDC_PUBLIC_KEY / AKTA_OIDC_PUBLIC_KEY_FILE)"
        )

    # Defense-in-depth clock check even when library already verified exp.
    ts = now if now is not None else time.time()
    exp = claims.get("exp")
    if exp is not None and float(exp) < ts - 30:
        raise ValueError("OIDC token expired")
    return dict(claims)


def _resolve_local_role(
    claims: Mapping[str, Any],
    *,
    role_claim: str,
    role_map: Mapping[str, str],
) -> str | None:
    """Map an IdP role claim through the configured local claim-to-role policy.

    Raw ``permissions`` / ``akta_permissions`` claims are never accepted as
    authorization without a local role mapping that yields ``ROLE_PERMISSIONS``.
    """
    if not role_map:
        return None
    if not role_claim:
        return None
    raw = claims.get(role_claim)
    if raw is None:
        return None
    local = role_map.get(str(raw))
    if local is None:
        return None
    if local not in ROLE_PERMISSIONS:
        return None
    return local


def authenticate_oidc_request(
    *,
    bearer_token: str | None,
    tenant_header: str | None,
    oidc_claims: dict[str, Any] | None = None,
    settings: OidcSettings | None = None,
    allow_unverified: bool = False,
) -> ServiceIdentity | None:
    """Resolve institutional identity from a verified OIDC token."""
    if not bearer_token and oidc_claims is None:
        return None

    try:
        cfg = settings if settings is not None else load_oidc_settings()
    except ValueError:
        return None

    try:
        if oidc_claims is not None:
            claims = dict(oidc_claims)
        else:
            claims = verify_oidc_bearer(
                bearer_token or "",
                issuer=cfg.issuer,
                audience=cfg.audience,
                jwks_url=cfg.jwks_url or None,
                public_key=cfg.public_key or None,
                algorithms=cfg.algorithms,
                allow_unverified=allow_unverified,
            )
    except Exception:
        return None

    caller_id = str(claims.get(cfg.subject_claim) or claims.get("sub") or "").strip()
    if not caller_id:
        return None

    tenant_id = ""
    if cfg.tenant_claim:
        tenant_id = str(claims.get(cfg.tenant_claim) or "").strip()
    if tenant_header and tenant_id and tenant_header != tenant_id:
        return None
    if tenant_header and not tenant_id:
        tenant_id = tenant_header
    if not tenant_id:
        return None

    role = _resolve_local_role(claims, role_claim=cfg.role_claim, role_map=cfg.role_map)
    if role is None:
        return None
    # Permissions come only from the local role policy — never from token claims.
    perms = ROLE_PERMISSIONS[role]
    claim_pairs = tuple(
        (str(k), str(v))
        for k, v in sorted(claims.items())
        if k in {"iss", "aud", "sub", cfg.tenant_claim, cfg.role_claim}
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
    oidc_settings: OidcSettings | None = None,
    allow_unverified_oidc: bool = False,
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
            settings=oidc_settings,
            allow_unverified=allow_unverified_oidc,
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
    oidc_settings: OidcSettings | None = None,
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

    errors: list[str] = []
    if oidc_configured is False:
        errors.append(
            "institutional-service requires OIDC configuration "
            "(issuer, audience, JWKS or pinned key, algorithms, "
            "tenant/role claim mapping, claim-to-role policy)"
        )
    else:
        errors.extend(institutional_oidc_config_errors(oidc_settings))

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
    "OidcSettings",
    "PILOT_SERVICE",
    "ROLE_PERMISSIONS",
    "STATIC_REGISTRY",
    "ServiceIdentity",
    "authenticate_oidc_request",
    "authenticate_request",
    "institutional_oidc_config_errors",
    "institutional_startup_errors",
    "load_oidc_settings",
    "load_service_identity_registry",
    "oidc_institutional_ready",
    "resolve_service_mode",
    "verify_oidc_bearer",
]
