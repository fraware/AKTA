"""Authenticated SCOPE authorization client (AKTA 1.2 P0-8).

Fetches signed authorization manifests and grant-status attestations with:

- OIDC workload bearer token or mTLS client certificates
- TLS certificate verification
- configured SCOPE audience
- tenant binding
- request timeout and response-size limits
- content-type verification
- bounded retries
- no cross-origin redirects
- signed-response shape validation

Transport authentication never substitutes for artifact signature verification;
callers must still verify signatures via trust stores.
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol
from urllib.parse import urljoin, urlparse

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_RESPONSE_BYTES = 1_048_576  # 1 MiB
DEFAULT_MAX_RETRIES = 2
RETRYABLE_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
ALLOWED_CONTENT_TYPES = frozenset(
    {
        "application/json",
        "application/jose+json",
        "application/jwt",
    }
)


class ScopeClientError(Exception):
    """SCOPE authorization client failure."""

    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        self.errors = list(errors or [])
        super().__init__(message)


class SignedAuthorizationManifest(dict[str, Any]):
    """Typed view of a signed SCOPE authorization manifest payload."""


class SignedGrantStatus(dict[str, Any]):
    """Typed view of a signed SCOPE grant-status attestation payload."""


class LedgerStatusVerifier(Protocol):
    """Authenticated direct ledger verifier with the same status interface."""

    def get_status(self, grant_id: str) -> SignedGrantStatus: ...


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class ScopeClientConfig:
    """Transport and policy controls for ScopeAuthorizationClient."""

    manifest_url: str | None = None
    status_url: str | None = None
    oidc_token: str | None = None
    oidc_token_provider: Callable[[], str] | None = None
    mtls_cert_file: str | None = None
    mtls_key_file: str | None = None
    ca_bundle: str | None = None
    verify_tls: bool = True
    audience: str | None = None
    tenant_id: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_retries: int = DEFAULT_MAX_RETRIES
    require_transport_auth: bool = False
    extra_headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> ScopeClientConfig:
        token = os.environ.get("AKTA_SCOPE_OIDC_TOKEN", "").strip() or None
        return cls(
            manifest_url=(
                os.environ.get("SCOPE_AUTHORIZATION_MANIFEST_URL", "").strip() or None
            ),
            status_url=os.environ.get("SCOPE_GRANT_STATUS_URL", "").strip() or None,
            oidc_token=token,
            mtls_cert_file=(
                os.environ.get("AKTA_SCOPE_MTLS_CERT_FILE", "").strip() or None
            ),
            mtls_key_file=(
                os.environ.get("AKTA_SCOPE_MTLS_KEY_FILE", "").strip() or None
            ),
            ca_bundle=os.environ.get("AKTA_SCOPE_CA_BUNDLE", "").strip() or None,
            verify_tls=not _env_bool("AKTA_SCOPE_TLS_INSECURE", False),
            audience=os.environ.get("AKTA_SCOPE_AUDIENCE", "").strip() or None,
            tenant_id=os.environ.get("AKTA_SCOPE_TENANT_ID", "").strip() or None,
            timeout_seconds=_env_float(
                "AKTA_SCOPE_CLIENT_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS
            ),
            max_response_bytes=_env_int(
                "AKTA_SCOPE_CLIENT_MAX_RESPONSE_BYTES", DEFAULT_MAX_RESPONSE_BYTES
            ),
            max_retries=_env_int(
                "AKTA_SCOPE_CLIENT_MAX_RETRIES", DEFAULT_MAX_RETRIES
            ),
            require_transport_auth=_env_bool(
                "AKTA_SCOPE_CLIENT_REQUIRE_AUTH", False
            ),
        )


class _NoCrossOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects that change scheme/host/port."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        previous = urlparse(req.full_url)
        nxt = urlparse(urljoin(req.full_url, newurl))
        if (
            previous.scheme != nxt.scheme
            or previous.netloc.lower() != nxt.netloc.lower()
        ):
            raise ScopeClientError(
                "cross-origin redirect rejected by ScopeAuthorizationClient "
                f"({previous.netloc!r} -> {nxt.netloc!r})"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _origin_key(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    return (parsed.scheme.lower(), parsed.netloc.lower())


def _has_signed_manifest_shape(payload: dict[str, Any]) -> bool:
    return bool(
        payload.get("manifest_signature")
        or payload.get("signature")
        or payload.get("attestation_signature")
    ) and bool(
        payload.get("manifest_hash")
        or payload.get("signed_payload_hash")
        or payload.get("attestation_hash")
    )


def _has_signed_status_shape(payload: dict[str, Any]) -> bool:
    return bool(payload.get("attestation_signature") or payload.get("signature")) and bool(
        payload.get("attestation_hash")
        or payload.get("status_hash")
        or payload.get("signed_payload_hash")
        or payload.get("grant_hash")
    )


class ScopeAuthorizationClient:
    """Typed authenticated client for SCOPE manifest and status endpoints."""

    def __init__(
        self,
        config: ScopeClientConfig | None = None,
        *,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        self.config = config or ScopeClientConfig.from_env()
        self._opener = opener
        self._ssl_context = self._build_ssl_context()

    @classmethod
    def from_env(cls) -> ScopeAuthorizationClient | None:
        cfg = ScopeClientConfig.from_env()
        if not cfg.manifest_url and not cfg.status_url:
            return None
        return cls(cfg)

    def _build_ssl_context(self) -> ssl.SSLContext | None:
        cfg = self.config
        if not cfg.verify_tls and not (cfg.mtls_cert_file or cfg.mtls_key_file):
            # Explicit insecure mode (tests only).
            ctx = ssl._create_unverified_context()  # noqa: S323
            return ctx
        ctx = ssl.create_default_context()
        if cfg.ca_bundle:
            ctx.load_verify_locations(cafile=cfg.ca_bundle)
        if not cfg.verify_tls:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        cert = cfg.mtls_cert_file
        key = cfg.mtls_key_file
        if cert or key:
            if not cert or not key:
                raise ScopeClientError(
                    "mTLS requires both AKTA_SCOPE_MTLS_CERT_FILE and "
                    "AKTA_SCOPE_MTLS_KEY_FILE"
                )
            ctx.load_cert_chain(certfile=cert, keyfile=key)
        return ctx

    def _transport_auth_configured(self) -> bool:
        cfg = self.config
        if cfg.oidc_token or callable(cfg.oidc_token_provider):
            return True
        if cfg.mtls_cert_file and cfg.mtls_key_file:
            return True
        return False

    def _ensure_transport_auth(self) -> None:
        if self.config.require_transport_auth and not self._transport_auth_configured():
            raise ScopeClientError(
                "ScopeAuthorizationClient requires OIDC workload token or mTLS"
            )

    def _resolve_token(self) -> str | None:
        if callable(self.config.oidc_token_provider):
            token = self.config.oidc_token_provider()
            return str(token).strip() or None
        if self.config.oidc_token:
            return str(self.config.oidc_token).strip() or None
        return None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            **dict(self.config.extra_headers),
        }
        token = self._resolve_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if self.config.audience:
            headers["X-SCOPE-Audience"] = self.config.audience
        if self.config.tenant_id:
            headers["X-SCOPE-Tenant-Id"] = self.config.tenant_id
        return headers

    def _opener_for(self) -> urllib.request.OpenerDirector:
        if self._opener is not None:
            return self._opener
        handlers: list[Any] = [_NoCrossOriginRedirectHandler()]
        if self._ssl_context is not None:
            handlers.append(urllib.request.HTTPSHandler(context=self._ssl_context))
        return urllib.request.build_opener(*handlers)

    def _format_url(self, template: str, *, grant_id: str | None = None, manifest_hash: str | None = None) -> str:
        url = template.strip()
        if grant_id is not None:
            if "{grant_id}" in url:
                url = url.format(grant_id=grant_id)
            elif not url.rstrip("/").endswith(grant_id):
                url = f"{url.rstrip('/')}/{grant_id}"
        if manifest_hash is not None:
            digest = manifest_hash.removeprefix("sha256:")
            if "{manifest_hash}" in url:
                url = url.format(manifest_hash=manifest_hash)
            elif "{hash}" in url:
                url = url.format(hash=manifest_hash)
            else:
                url = f"{url.rstrip('/')}/{digest}"
        return url

    def _read_limited(self, resp: Any) -> bytes:
        max_bytes = max(1, int(self.config.max_response_bytes))
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = resp.read(min(65536, max_bytes - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ScopeClientError(
                    f"SCOPE response exceeds max size ({max_bytes} bytes)"
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _validate_content_type(self, content_type: str | None) -> None:
        if not content_type:
            raise ScopeClientError("SCOPE response missing Content-Type")
        media = content_type.split(";", 1)[0].strip().lower()
        if media not in ALLOWED_CONTENT_TYPES:
            raise ScopeClientError(
                f"SCOPE response Content-Type not allowed: {content_type!r}"
            )

    def _get_json(self, url: str) -> dict[str, Any]:
        self._ensure_transport_auth()
        if urlparse(url).scheme not in {"http", "https"}:
            raise ScopeClientError(f"unsupported SCOPE URL scheme: {url!r}")
        if urlparse(url).scheme == "https" and self._ssl_context is None:
            raise ScopeClientError("TLS context required for https SCOPE endpoints")

        opener = self._opener_for()
        headers = self._headers()
        attempts = max(0, int(self.config.max_retries)) + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            req = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with opener.open(req, timeout=self.config.timeout_seconds) as resp:  # noqa: S310
                    final_url = getattr(resp, "geturl", lambda: url)()
                    if _origin_key(final_url) != _origin_key(url):
                        raise ScopeClientError(
                            "cross-origin redirect detected in final response URL"
                        )
                    self._validate_content_type(resp.headers.get("Content-Type"))
                    raw = self._read_limited(resp)
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ScopeClientError(
                        f"SCOPE response is not valid JSON: {exc}"
                    ) from exc
                if not isinstance(payload, dict):
                    raise ScopeClientError("SCOPE response JSON must be an object")
                return payload
            except ScopeClientError:
                raise
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code in RETRYABLE_HTTP_STATUS and attempt + 1 < attempts:
                    time.sleep(min(0.05 * (2**attempt), 0.5))
                    continue
                raise ScopeClientError(
                    f"SCOPE HTTP error {exc.code} for {url}"
                ) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(min(0.05 * (2**attempt), 0.5))
                    continue
                raise ScopeClientError(f"SCOPE request failed: {exc}") from exc

        raise ScopeClientError(
            f"SCOPE request failed after retries: {last_error}"
        )

    def _check_audience_and_tenant(self, payload: dict[str, Any]) -> None:
        cfg = self.config
        if cfg.audience:
            declared = (
                payload.get("audience")
                or (payload.get("constraints") or {}).get("audience")
            )
            if declared is not None and str(declared) != str(cfg.audience):
                raise ScopeClientError(
                    f"SCOPE response audience mismatch ({declared!r} != {cfg.audience!r})"
                )
        if cfg.tenant_id:
            declared_tenant = payload.get("tenant_id") or (
                (payload.get("environment") or {}).get("tenant_id")
            )
            if declared_tenant is not None and str(declared_tenant) != str(cfg.tenant_id):
                raise ScopeClientError(
                    f"SCOPE response tenant mismatch "
                    f"({declared_tenant!r} != {cfg.tenant_id!r})"
                )

    def get_manifest(self, manifest_hash: str) -> SignedAuthorizationManifest:
        if not self.config.manifest_url:
            raise ScopeClientError("SCOPE authorization manifest URL not configured")
        url = self._format_url(self.config.manifest_url, manifest_hash=manifest_hash)
        payload = self._get_json(url)
        self._check_audience_and_tenant(payload)
        if not _has_signed_manifest_shape(payload):
            raise ScopeClientError(
                "SCOPE manifest response missing signature/hash fields "
                "(transport auth is not a substitute for artifact signatures)"
            )
        declared = payload.get("manifest_hash") or payload.get("signed_payload_hash")
        if declared and str(declared) != str(manifest_hash):
            raise ScopeClientError(
                "SCOPE manifest hash does not match requested hash "
                f"({declared!r} != {manifest_hash!r})"
            )
        return SignedAuthorizationManifest(payload)

    def get_status(self, grant_id: str) -> SignedGrantStatus:
        if not self.config.status_url:
            raise ScopeClientError("SCOPE grant status URL not configured")
        url = self._format_url(self.config.status_url, grant_id=grant_id)
        payload = self._get_json(url)
        self._check_audience_and_tenant(payload)
        if not _has_signed_status_shape(payload):
            raise ScopeClientError(
                "SCOPE status response missing attestation signature/hash "
                "(transport auth is not a substitute for artifact signatures)"
            )
        response_grant = payload.get("grant_id")
        if response_grant is not None and str(response_grant) != str(grant_id):
            raise ScopeClientError(
                f"SCOPE status grant_id mismatch ({response_grant!r} != {grant_id!r})"
            )
        return SignedGrantStatus(payload)


__all__ = [
    "LedgerStatusVerifier",
    "ScopeAuthorizationClient",
    "ScopeClientConfig",
    "ScopeClientError",
    "SignedAuthorizationManifest",
    "SignedGrantStatus",
]
