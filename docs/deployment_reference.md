# Deployment reference (v1.0)

AKTA v1.0 ships a **reference** REST and MCP adapter baseline — not a production HA service.

## REST (`akta-rest`)

- Endpoints under `/v0/` (health, evaluate, records, export, artifacts)
- Structured responses include `request_id` (from `X-Request-ID` header or generated UUID)
- Error envelope: `error_code`, `detail`, `request_id` (filesystem paths sanitized)
- Default bind: loopback (`127.0.0.1`). Non-loopback binds require `AKTA_REST_API_KEY` or `AKTA_REST_SERVICE_TOKENS`
- Production mode (`AKTA_REST_PRODUCTION=1` / `--production`): authenticated service identities required even on loopback
- Caller-supplied filesystem paths (`decision_path`, `out_dir`, policy/overlay paths) are rejected; policy dirs are server-controlled
- Request body limit: `AKTA_REST_MAX_BODY_BYTES` (default 1 MiB)
- Rate limiting: `AKTA_REST_RATE_LIMIT` (default 120/min), concurrency-safe sliding window
- `X-Forwarded-For` is ignored unless `AKTA_REST_TRUSTED_PROXY=1` (TLS termination + trusted proxy required in production)

### TLS and trusted proxies

Terminate TLS at a reverse proxy (or load balancer). Enable `AKTA_REST_TRUSTED_PROXY=1` only when the proxy strips untrusted `X-Forwarded-For` and forwards the real client address. Do not expose the REST process directly on a public interface without TLS and service-token auth.

## MCP (`adapters/mcp/server.py`)

- Stdio JSON-RPC tools: `akta_evaluate`, `akta_evaluate_with_grant`, `akta_export`
- Errors include `request_id` matching JSON-RPC `id`

## Observability (optional)

Set `AKTA_OTEL_ENABLED=1` to emit OpenTelemetry spans when `opentelemetry-api` is installed. No hard dependency in v1.0.

## Agent harness

Use `AKTALangGraphMiddleware` with `SessionGrantStore` for multi-turn grant persistence. Grants auto-invalidate on expiry and evidence downgrade.

## Non-goals for v1.0

- High availability or horizontal scaling
- Auth federation / SSO
- Operational P7 autonomous operator support
