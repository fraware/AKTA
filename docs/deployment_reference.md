# Deployment reference (v1.0)

AKTA v1.0 ships a **reference** REST and MCP adapter baseline — not a production HA service.

## REST (`akta-rest`)

- Endpoints under `/v0/` (health, gate, record, export)
- Structured responses include `request_id` (from `X-Request-ID` header or generated UUID)
- Error envelope: `error_code`, `detail`, `request_id`
- Optional `AKTA_REST_API_KEY` for simple API-key auth
- Rate limiting via env `AKTA_REST_RATE_LIMIT` (default 120/min)

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
