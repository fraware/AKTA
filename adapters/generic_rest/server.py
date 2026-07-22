"""AKTA generic REST API server (v1.0 service boundary).

Localhost-only is the default development posture. Production mode requires
authenticated service identities, rejects caller filesystem paths, enforces
request-size limits, and does not trust arbitrary X-Forwarded-For headers.

TLS termination and trusted-proxy configuration are deployment concerns —
see docs/deployment_reference.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from collections import defaultdict, deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from importlib.metadata import version as pkg_version

from akta.cards import validate_card
from akta.context import AKTAContext
from akta.errors import AKTAError, SchemaValidationError
from akta.gate import AKTAGate
from akta.records import AKTADecision
from adapters.pcs.export_artifact import export_pcs_bundle
from adapters.pf_core.export_obligation import export_pf_obligation

logger = logging.getLogger(__name__)

_RATE_WINDOW_SEC = 60.0
_RATE_LIMIT_DEFAULT = 120
_MAX_BODY_DEFAULT = 1_048_576  # 1 MiB
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


class _RateLimiter:
    """Bounded, concurrency-safe sliding-window rate limiter."""

    def __init__(self, limit: int, *, window_sec: float = _RATE_WINDOW_SEC) -> None:
        self.limit = limit
        self.window_sec = window_sec
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, client_key: str) -> bool:
        now = time.monotonic()
        window_start = now - self.window_sec
        with self._lock:
            hits = self._hits[client_key]
            while hits and hits[0] < window_start:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            # Bound memory: drop idle keys opportunistically
            if len(self._hits) > 10_000:
                stale = [k for k, v in self._hits.items() if not v or v[-1] < window_start]
                for k in stale[:1000]:
                    self._hits.pop(k, None)
            return True


def _is_loopback(host: str) -> bool:
    h = (host or "").strip().lower()
    if h.startswith("::ffff:"):
        h = h.split("::ffff:", 1)[-1]
    return h in _LOOPBACK or h.startswith("127.")


def _sanitize_error_detail(detail: str | None) -> str | None:
    if not detail:
        return None
    # Strip absolute Windows/Unix paths from client-visible errors.
    cleaned = detail
    for sep in ("\\", "/"):
        if sep in cleaned and (":" in cleaned or cleaned.startswith(sep)):
            return "request failed"
    if "No such file" in cleaned or "FileNotFoundError" in cleaned:
        return "request failed"
    return cleaned[:500]


class AKTARESTHandler(BaseHTTPRequestHandler):
    """HTTP handler for AKTA REST endpoints."""

    gate: AKTAGate | None = None
    policy_dir: Path = Path("policy")
    overlays_dir: Path = Path("overlays")
    api_key: str | None = None
    service_tokens: frozenset[str] = frozenset()
    rate_limiter: _RateLimiter | None = None
    production_mode: bool = False
    bind_host: str = "127.0.0.1"
    max_body_bytes: int = _MAX_BODY_DEFAULT
    trusted_proxy: bool = False
    artifact_store: dict[str, dict[str, Any]] = {}
    audit_log: list[dict[str, Any]] = []

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), format % args)

    def _peer_ip(self) -> str:
        return self.client_address[0]

    def _client_key(self) -> str:
        # Never trust arbitrary X-Forwarded-For unless explicitly behind a trusted proxy.
        if self.trusted_proxy and self.production_mode:
            forwarded = self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            if forwarded:
                return forwarded
        return self._peer_ip()

    def _audit(self, event: str, **fields: Any) -> None:
        entry = {
            "event": event,
            "ts": time.time(),
            "request_id": self.headers.get("X-Request-ID"),
            "peer": self._peer_ip(),
            **fields,
        }
        self.audit_log.append(entry)
        logger.info("audit %s", json.dumps(entry, default=str))

    def _extract_bearer_or_key(self) -> str | None:
        api_key = self.headers.get("X-API-Key")
        if api_key:
            return api_key.strip()
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return None

    def _check_auth_and_rate(self) -> bool:
        peer = self._peer_ip()
        loopback = _is_loopback(peer) and _is_loopback(self.bind_host)
        token = self._extract_bearer_or_key()

        require_auth = self.production_mode or (not loopback) or bool(self.api_key) or bool(self.service_tokens)
        if require_auth and not loopback and not (self.api_key or self.service_tokens):
            self._send_error_json(
                HTTPStatus.UNAUTHORIZED,
                "auth_required",
                "Authentication required for non-loopback bindings",
            )
            self._audit("auth_rejected", reason="non_loopback_without_server_credentials")
            return False

        if self.production_mode or (not loopback):
            # Production / off-loopback: require service identity token.
            accepted = set(self.service_tokens)
            if self.api_key:
                accepted.add(self.api_key)
            if not token or token not in accepted:
                self._send_error_json(
                    HTTPStatus.UNAUTHORIZED,
                    "unauthorized",
                    "Valid service identity required",
                )
                self._audit("auth_rejected", reason="invalid_or_missing_service_token")
                return False
        elif self.api_key:
            if token != self.api_key:
                self._send_error_json(
                    HTTPStatus.UNAUTHORIZED,
                    "unauthorized",
                    "Invalid or missing API key",
                )
                return False

        if self.rate_limiter and not self.rate_limiter.allow(self._client_key()):
            self._send_error_json(HTTPStatus.TOO_MANY_REQUESTS, "rate_limited", "Rate limit exceeded")
            self._audit("rate_limited", client_key=self._client_key())
            return False
        return True

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length < 0:
            raise ValueError("Invalid Content-Length")
        if length > self.max_body_bytes:
            raise ValueError("request_too_large")
        raw = self.rfile.read(length) if length else b"{}"
        if len(raw) > self.max_body_bytes:
            raise ValueError("request_too_large")
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON body: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object.")
        # Reject caller-supplied filesystem path fields in production/service mode.
        banned = ("decision_path", "out_dir", "policy_dir", "overlays_dir", "record_path")
        present = [k for k in banned if k in data]
        if present:
            raise ValueError(f"caller_filesystem_paths_forbidden:{','.join(present)}")
        return data

    def _request_id(self) -> str:
        return self.headers.get("X-Request-ID") or str(uuid.uuid4())

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        envelope = {"request_id": self._request_id(), **payload}
        body = json.dumps(envelope, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, code: str, detail: str | None = None) -> None:
        payload: dict[str, Any] = {"error_code": code, "error": code}
        safe = _sanitize_error_detail(detail)
        if safe:
            payload["detail"] = safe
        self._send_json(status, payload)

    def _gate(self) -> AKTAGate:
        if self.gate is None:
            self.gate = AKTAGate.from_policy_dir(self.policy_dir, overlays_dir=self.overlays_dir)
        return self.gate

    def _store_artifact(self, kind: str, data: dict[str, Any]) -> str:
        artifact_id = f"AKTA-{kind.upper()}-{uuid.uuid4().hex[:12]}"
        self.artifact_store[artifact_id] = {"kind": kind, "data": data}
        return artifact_id

    def do_GET(self) -> None:
        if not self._check_auth_and_rate():
            return
        path = urlparse(self.path).path
        try:
            if path == "/v0/health":
                self._send_json(HTTPStatus.OK, {
                    "status": "ok",
                    "version": pkg_version("akta-protocol"),
                    "api_version": "v1.0",
                    "production_mode": self.production_mode,
                })
            elif path == "/v0/openapi":
                self._send_json(HTTPStatus.OK, {
                    "api_version": "v1.0",
                    "spec": "adapters/generic_rest/openapi.yaml",
                })
            elif path == "/v0/policy":
                gate = self._gate()
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "policy_version": gate.policy.version,
                        "policy_hash": gate.policy.policy_hash,
                        "tool_registry_hash": gate.policy.tool_registry_hash,
                        "policy": gate.policy.policy_binding(),
                        "supported_profiles": [
                            p for p, meta in gate.policy.deployment_profiles.get("profiles", {}).items()
                            if meta.get("supported", True)
                        ],
                    },
                )
            elif path.startswith("/v0/artifacts/"):
                artifact_id = path.rsplit("/", 1)[-1]
                artifact = self.artifact_store.get(artifact_id)
                if not artifact:
                    self._send_error_json(HTTPStatus.NOT_FOUND, "artifact_not_found")
                    return
                self._send_json(HTTPStatus.OK, {"artifact_id": artifact_id, **artifact})
            else:
                self._send_error_json(HTTPStatus.NOT_FOUND, "not_found")
        except Exception as exc:
            logger.exception("GET failed")
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", str(exc))

    def do_POST(self) -> None:
        if not self._check_auth_and_rate():
            return
        path = urlparse(self.path).path
        try:
            body = self._read_json_body()
            if path == "/v0/evaluate":
                self._handle_evaluate(body)
            elif path == "/v0/records":
                self._handle_records(body)
            elif path == "/v0/cards/validate":
                self._handle_card_validate(body)
            elif path == "/v0/export/pcs":
                self._handle_export_pcs(body)
            elif path == "/v0/export/pf":
                self._handle_export_pf(body)
            else:
                self._send_error_json(HTTPStatus.NOT_FOUND, "not_found")
        except ValueError as exc:
            msg = str(exc)
            code = "bad_request"
            if "request_too_large" in msg:
                code = "request_too_large"
                self._send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, code, msg)
                return
            if "caller_filesystem_paths_forbidden" in msg:
                code = "caller_filesystem_paths_forbidden"
            self._send_error_json(HTTPStatus.BAD_REQUEST, code, msg)
        except SchemaValidationError as exc:
            self._send_error_json(HTTPStatus.UNPROCESSABLE_ENTITY, "schema_validation_error", str(exc))
        except AKTAError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "akta_error", str(exc))
        except Exception as exc:
            logger.exception("POST failed")
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", str(exc))

    def _handle_evaluate(self, body: dict[str, Any]) -> None:
        required = ("requested_tool",)
        missing = [k for k in required if k not in body]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

        ctx_data = body.get("context", {})
        if "vsa_report" in body:
            from adapters.vsa.import_report import import_vsa_report

            vsa_ctx = import_vsa_report(body["vsa_report"])
            ctx_data = {**vsa_ctx, **ctx_data}

        decision = self._gate().evaluate(
            ai_output=body.get("ai_output", ""),
            requested_tool=body["requested_tool"],
            requested_action=body.get("requested_action", body["requested_tool"]),
            context=AKTAContext.from_dict(ctx_data),
            deployment_profile=body.get("deployment_profile", "P2_analysis_assistant"),
            domain_overlay=body.get("domain_overlay"),
        )
        d = decision.to_dict()
        artifact_id = self._store_artifact("decision", d)
        d["artifact_id"] = artifact_id
        self._audit("evaluate", artifact_id=artifact_id, admissibility=d.get("admissibility"))
        self._send_json(HTTPStatus.OK, d)

    def _handle_records(self, body: dict[str, Any]) -> None:
        if "decision" in body:
            decision = AKTADecision(body["decision"])
        elif "decision_artifact_id" in body:
            stored = self.artifact_store.get(str(body["decision_artifact_id"]))
            if not stored or stored.get("kind") != "decision":
                raise ValueError("unknown decision_artifact_id")
            decision = AKTADecision(stored["data"])
        else:
            raise ValueError("Provide 'decision' object or 'decision_artifact_id'.")

        context = body.get("context", {})
        record = decision.to_record(ai_output=body.get("ai_output"), context=context)
        if body.get("validate", True):
            from akta.records import validate_against_schema

            validate_against_schema(record.to_dict(), "akta_record.schema.json")
        payload = record.to_dict()
        artifact_id = self._store_artifact("record", payload)
        payload["artifact_id"] = artifact_id
        self._audit("record_created", artifact_id=artifact_id)
        self._send_json(HTTPStatus.OK, payload)

    def _handle_card_validate(self, body: dict[str, Any]) -> None:
        card = body.get("card")
        if not isinstance(card, dict):
            raise ValueError("Field 'card' must be an object.")
        validate_card(card)
        self._send_json(
            HTTPStatus.OK,
            {"valid": True, "system_name": card.get("system_name", "unknown")},
        )

    def _handle_export_pcs(self, body: dict[str, Any]) -> None:
        record_data = body.get("record")
        if not isinstance(record_data, dict):
            raise ValueError("Field 'record' must be an AKTA Record object.")
        with tempfile.TemporaryDirectory() as tmp:
            export_pcs_bundle(record_data, Path(tmp))
            manifest = json.loads((Path(tmp) / "manifest.json").read_text(encoding="utf-8"))
        artifact_id = self._store_artifact("pcs_manifest", manifest)
        self._audit("export_pcs", artifact_id=artifact_id)
        self._send_json(HTTPStatus.OK, {
            "exported": True,
            "manifest": manifest,
            "artifact_id": artifact_id,
        })

    def _handle_export_pf(self, body: dict[str, Any]) -> None:
        record_data = body.get("record")
        if not isinstance(record_data, dict):
            raise ValueError("Field 'record' must be an AKTA Record object.")
        with tempfile.TemporaryDirectory() as tmp:
            path = export_pf_obligation(record_data, tmp)
            obligation = json.loads(path.read_text(encoding="utf-8"))
        artifact_id = self._store_artifact("pf_obligation", obligation)
        self._audit("export_pf", artifact_id=artifact_id)
        self._send_json(HTTPStatus.OK, {
            "exported": True,
            "obligation": obligation,
            "artifact_id": artifact_id,
        })


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    policy_dir: str | Path = "policy",
    overlays_dir: str | Path = "overlays",
    *,
    api_key: str | None = None,
    rate_limit: int | None = None,
    production_mode: bool | None = None,
    service_tokens: list[str] | None = None,
    max_body_bytes: int | None = None,
    trusted_proxy: bool | None = None,
) -> ThreadingHTTPServer:
    """Create configured AKTA REST server.

    Policy/overlay directories are server-controlled (constructor args / env), never
    accepted from request bodies.
    """
    policy_dir = Path(policy_dir)
    overlays_dir = Path(overlays_dir)
    resolved_api_key = api_key or os.environ.get("AKTA_REST_API_KEY") or None
    limit = rate_limit if rate_limit is not None else int(os.environ.get("AKTA_REST_RATE_LIMIT", _RATE_LIMIT_DEFAULT))
    prod = production_mode if production_mode is not None else (
        os.environ.get("AKTA_REST_PRODUCTION", "").lower() in ("1", "true", "yes")
        or os.environ.get("AKTA_PRODUCTION_MODE", "").lower() in ("1", "true", "yes")
    )
    tokens_env = os.environ.get("AKTA_REST_SERVICE_TOKENS", "")
    tokens = set(service_tokens or [])
    tokens.update(t.strip() for t in tokens_env.split(",") if t.strip())
    max_body = max_body_bytes if max_body_bytes is not None else int(
        os.environ.get("AKTA_REST_MAX_BODY_BYTES", _MAX_BODY_DEFAULT)
    )
    trust_proxy = trusted_proxy if trusted_proxy is not None else (
        os.environ.get("AKTA_REST_TRUSTED_PROXY", "").lower() in ("1", "true", "yes")
    )

    if not _is_loopback(host) and not (resolved_api_key or tokens):
        raise ValueError(
            "Non-loopback REST bind requires AKTA_REST_API_KEY or AKTA_REST_SERVICE_TOKENS"
        )

    class Handler(AKTARESTHandler):
        pass

    Handler.policy_dir = policy_dir
    Handler.overlays_dir = overlays_dir
    Handler.api_key = resolved_api_key
    Handler.service_tokens = frozenset(tokens)
    Handler.rate_limiter = _RateLimiter(limit) if limit > 0 else None
    Handler.production_mode = bool(prod)
    Handler.bind_host = host
    Handler.max_body_bytes = max_body
    Handler.trusted_proxy = bool(trust_proxy)
    Handler.artifact_store = {}
    Handler.audit_log = []
    Handler.gate = AKTAGate.from_policy_dir(policy_dir, overlays_dir=overlays_dir)
    return ThreadingHTTPServer((host, port), Handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AKTA REST API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--policy-dir", default="policy")
    parser.add_argument("--overlays-dir", default="overlays")
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args(argv)

    server = create_server(
        args.host,
        args.port,
        args.policy_dir,
        args.overlays_dir,
        production_mode=args.production or None,
    )
    print(f"AKTA REST server listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
