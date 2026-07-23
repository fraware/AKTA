# Deployment reference (v1.1 / WS13)

AKTA ships a **reference** REST and MCP adapter baseline — not a production HA service.
Beta designation is retained; this is not a claim of production readiness for SCOPE-authorized action.

## REST modes (P1-C / WS13)

| Mode | Env / flag | Posture |
|------|------------|---------|
| `development-local` | default / `AKTA_REST_MODE=development-local` | Loopback-friendly; in-memory artifact/audit stores; optional API key |
| `pilot-service` | `AKTA_REST_MODE=pilot-service` (alias: `static-registry`) | Credential-digest identity registry + file (or CI sqlite) stores; non-institutional |
| `institutional-service` | `AKTA_REST_MODE=institutional-service` | OIDC issuer+audience verification, PostgreSQL artifact/audit stores, trusted proxy, policy manifest verification |

`AKTA_REST_PRODUCTION=1` still means “require auth on loopback” inside development-local.
It does **not** equal institutional-service identity. Static bearer-token equality alone is
rejected as institutional identity.

### Pilot-service requirements

- Verified service identity registry (`AKTA_REST_IDENTITY_REGISTRY`) with credential digests
- Role / API permissions and `X-AKTA-Tenant` binding
- Persistent file artifact store + append-only audit ledger (`AKTA_REST_DATA_DIR`)
- Optional CI fallback: `AKTA_REST_USE_SQLITE=1` (never for institutional production)

### Institutional-service requirements

- OIDC issuer + audience (`AKTA_OIDC_ISSUER`, `AKTA_OIDC_AUDIENCE`) and JWKS URL (`AKTA_OIDC_JWKS_URL`)
- Optional claim mapping: `AKTA_OIDC_TENANT_CLAIM`, `AKTA_OIDC_ROLE_CLAIM`, `AKTA_OIDC_SUBJECT_CLAIM`
- PostgreSQL DSN: `AKTA_REST_DATABASE_URL` (or `DATABASE_URL`)
- TLS termination + `AKTA_REST_TRUSTED_PROXY=1`
- Bounded request body (`AKTA_REST_MAX_BODY_BYTES`) and rate limiting (`AKTA_REST_RATE_LIMIT`)
- Policy manifest verification on startup
- `/records` requires `decision_artifact_id` (inline decision bodies rejected)
- PF/PCS export requires `record_artifact_id` (inline record bodies rejected)

### Optional dependencies

Install institutional extras:

```bash
pip install 'akta-protocol[rest]'
# provides: PyJWT, psycopg[binary]
```

Without these packages, institutional OIDC/PostgreSQL paths fail closed with an explicit import error.
CI may exercise pilot-service with file/sqlite stores and mock OIDC claims in unit tests.

## REST (`akta-rest`)

- Endpoints under `/v0/` (health, evaluate, records, export, artifacts)
- Structured responses include `request_id` (from `X-Request-ID` header or generated UUID)
- Error envelope: `error_code`, `detail`, `request_id` (filesystem paths sanitized)
- Default bind: loopback (`127.0.0.1`). Non-loopback binds require credentials / OIDC
- Caller-supplied filesystem paths (`decision_path`, `out_dir`, policy/overlay paths) are rejected; policy dirs are server-controlled
- Artifact retrieval is bound to tenant + caller permissions (admin/auditor may read tenant-scoped artifacts)
- Artifact IDs are collision-resistant; stores record artifact hashes, schema versions, and source linkage
- Audit ledgers are hash-chained (`prev_hash` / `entry_hash`)

### TLS and trusted proxies

Terminate TLS at a reverse proxy (or load balancer). Enable `AKTA_REST_TRUSTED_PROXY=1` only when the proxy strips untrusted `X-Forwarded-For` and forwards the real client address. Do not expose the REST process directly on a public interface without TLS and verified service identity.

### Institutional trust store

See [institutional_trust_store.md](institutional_trust_store.md) for grant-issuer / status / manifest
registries. Production grant crypto fails closed on empty registries.

## MCP (`adapters/mcp/server.py`)

- Stdio JSON-RPC tools: `akta_evaluate`, `akta_evaluate_with_grant`, `akta_export`
- Errors include `request_id` matching JSON-RPC `id`

## Observability (optional)

Set `AKTA_OTEL_ENABLED=1` to emit OpenTelemetry spans when `opentelemetry-api` is installed. No hard dependency in v1.0.

## Agent harness

Use `AKTALangGraphMiddleware` with `SessionGrantStore` for multi-turn grant persistence. Grants auto-invalidate on expiry and evidence downgrade.

## Institutional pilot stages (P1-E)

`AKTA_PILOT_STAGE=stage1_shadow|stage2_draft_only|stage3_validation` (see `akta/pilot_workflow.py`).
Stage 3 requires real SCOPE identity, signed grant, full verification, PF proof, PCS package, and transactional ledger — fail closed if any missing. Hard exclusions: physical robot, clinical intervention, high-risk bio, hazardous chemical, unreviewed publication claims.

## Non-goals for v1.0

- High availability or horizontal scaling
- Auth federation / SSO as a product beyond OIDC token verification
- Operational P7 autonomous operator support
