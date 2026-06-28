"""AKTA generic REST API server (v0.6)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
import time
from collections import defaultdict
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
from akta.records import AKTADecision, AKTARecord
from adapters.pcs.export_artifact import export_pcs_bundle
from adapters.pf_core.export_obligation import export_pf_obligation

logger = logging.getLogger(__name__)

_RATE_WINDOW_SEC = 60.0
_RATE_LIMIT_DEFAULT = 120


class _RateLimiter:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, client_key: str) -> bool:
        now = time.monotonic()
        window_start = now - _RATE_WINDOW_SEC
        hits = [t for t in self._hits[client_key] if t >= window_start]
        if len(hits) >= self.limit:
            self._hits[client_key] = hits
            return False
        hits.append(now)
        self._hits[client_key] = hits
        return True


class AKTARESTHandler(BaseHTTPRequestHandler):
    """HTTP handler for AKTA v0 REST endpoints."""

    gate: AKTAGate | None = None
    policy_dir: Path = Path("policy")
    overlays_dir: Path = Path("overlays")
    api_key: str | None = None
    rate_limiter: _RateLimiter | None = None

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), format % args)

    def _client_key(self) -> str:
        return self.headers.get("X-Forwarded-For") or self.client_address[0]

    def _check_auth_and_rate(self) -> bool:
        if self.api_key:
            provided = self.headers.get("X-API-Key") or self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if provided != self.api_key:
                self._send_error_json(HTTPStatus.UNAUTHORIZED, "unauthorized", "Invalid or missing API key")
                return False
        if self.rate_limiter and not self.rate_limiter.allow(self._client_key()):
            self._send_error_json(HTTPStatus.TOO_MANY_REQUESTS, "rate_limited", "Rate limit exceeded")
            return False
        return True

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON body: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object.")
        return data

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, message: str, detail: str | None = None) -> None:
        payload: dict[str, Any] = {"error": message}
        if detail:
            payload["detail"] = detail
        self._send_json(status, payload)

    def _gate(self) -> AKTAGate:
        if self.gate is None:
            self.gate = AKTAGate.from_policy_dir(self.policy_dir, overlays_dir=self.overlays_dir)
        return self.gate

    def do_GET(self) -> None:
        if not self._check_auth_and_rate():
            return
        path = urlparse(self.path).path
        try:
            if path == "/v0/health":
                self._send_json(HTTPStatus.OK, {
                    "status": "ok",
                    "version": pkg_version("akta-protocol"),
                    "api_version": "v0.6",
                })
            elif path == "/v0/openapi":
                spec_path = Path(__file__).resolve().parent / "openapi.yaml"
                self._send_json(HTTPStatus.OK, {"openapi_path": str(spec_path), "api_version": "v0.6"})
            elif path == "/v0/policy":
                gate = self._gate()
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "policy_version": gate.policy.version,
                        "policy_hash": gate.policy.policy_hash,
                        "tool_registry_hash": gate.policy.tool_registry_hash,
                        "supported_profiles": [
                            p for p, meta in gate.policy.deployment_profiles.get("profiles", {}).items()
                            if meta.get("supported", True)
                        ],
                    },
                )
            else:
                self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", f"Unknown path: {path}")
        except Exception as exc:
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
                self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", f"Unknown path: {path}")
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))
        except SchemaValidationError as exc:
            self._send_error_json(HTTPStatus.UNPROCESSABLE_ENTITY, "schema_validation_error", str(exc))
        except AKTAError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "akta_error", str(exc))
        except Exception as exc:
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
        self._send_json(HTTPStatus.OK, d)

    def _handle_records(self, body: dict[str, Any]) -> None:
        if "decision" in body:
            decision = AKTADecision(body["decision"])
        elif "decision_path" in body:
            decision = AKTADecision.from_file(body["decision_path"])
        else:
            raise ValueError("Provide 'decision' object or run /v0/evaluate first.")

        context = body.get("context", {})
        record = decision.to_record(ai_output=body.get("ai_output"), context=context)
        if body.get("validate", True):
            from akta.records import validate_against_schema

            validate_against_schema(record.to_dict(), "akta_record.schema.json")
        self._send_json(HTTPStatus.OK, record.to_dict())

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
        out_dir = body.get("out_dir")
        with tempfile.TemporaryDirectory() as tmp:
            export_path = Path(out_dir) if out_dir else Path(tmp)
            export_pcs_bundle(record_data, export_path)
            manifest = json.loads((export_path / "manifest.json").read_text(encoding="utf-8"))
        self._send_json(HTTPStatus.OK, {"exported": True, "manifest": manifest})

    def _handle_export_pf(self, body: dict[str, Any]) -> None:
        record_data = body.get("record")
        if not isinstance(record_data, dict):
            raise ValueError("Field 'record' must be an AKTA Record object.")
        with tempfile.TemporaryDirectory() as tmp:
            path = export_pf_obligation(record_data, tmp)
            obligation = json.loads(path.read_text(encoding="utf-8"))
        self._send_json(HTTPStatus.OK, {"exported": True, "obligation": obligation})


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    policy_dir: str | Path = "policy",
    overlays_dir: str | Path = "overlays",
    *,
    api_key: str | None = None,
    rate_limit: int | None = None,
) -> ThreadingHTTPServer:
    """Create configured AKTA REST server."""
    policy_dir = Path(policy_dir)
    overlays_dir = Path(overlays_dir)
    resolved_api_key = api_key or os.environ.get("AKTA_REST_API_KEY") or None
    limit = rate_limit if rate_limit is not None else int(os.environ.get("AKTA_REST_RATE_LIMIT", _RATE_LIMIT_DEFAULT))

    class Handler(AKTARESTHandler):
        pass

    Handler.policy_dir = policy_dir
    Handler.overlays_dir = overlays_dir
    Handler.api_key = resolved_api_key
    Handler.rate_limiter = _RateLimiter(limit) if limit > 0 else None
    Handler.gate = AKTAGate.from_policy_dir(policy_dir, overlays_dir=overlays_dir)
    return ThreadingHTTPServer((host, port), Handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AKTA REST API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--policy-dir", default="policy")
    parser.add_argument("--overlays-dir", default="overlays")
    args = parser.parse_args(argv)

    server = create_server(args.host, args.port, args.policy_dir, args.overlays_dir)
    print(f"AKTA REST server listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
