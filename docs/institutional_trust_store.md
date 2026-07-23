# Institutional trust store (issuer key registry)

AKTA authenticates SCOPE grants against an **issuer public-key registry**.
Production and other institutional profiles **fail closed** when the registry
is empty, missing, or contains only revoked/expired keys.

Beta designation: this is a reference trust-binding mechanism, not a claim that
AKTA is production-ready for SCOPE-authorized action.

## Registry schema

Default file: `policy/scope_issuer_key_registry.yaml` (ships empty).

Each issuer entry supports:

| Field | Required | Notes |
|-------|----------|-------|
| `key_id` | yes | Stable issuer key identifier (also used as map key) |
| `status` | yes | `active` \| `revoked` \| `expired` \| `pending` |
| `algorithm` | yes | `Ed25519` only in v1 |
| public material | one of | `public_key_ref`, `public_key_pem`, or `public_key_file` |
| `valid_from` / `valid_until` | recommended | ISO-8601; outside window → reject |
| `issuer_identity` | optional | Human/org label; not a secret |
| `notes` | optional | Operational commentary |

SCOPE sibling `policy/reviewer_key_registry.yaml` entries (`reviewers:`) are
also accepted when discovered via `SCOPE_REPO_PATH`. Private key fields are
never loaded into the trust store.

## How institutions deploy

1. Generate or obtain an Ed25519 **issuer** keypair offline (HSM/KMS preferred).
2. Export **public** PEM only into an institutional registry file. Never commit
   private keys to the AKTA tree.
3. Point AKTA at that file:

```bash
export AKTA_TRUST_STORE_PATH=/etc/akta/issuer_key_registry.yaml
# optional alias:
export AKTA_ISSUER_KEY_REGISTRY=/etc/akta/issuer_key_registry.yaml
```

4. Enable crypto-required grant verification:

```bash
export AKTA_GRANT_MODE=production
# or:
export AKTA_REQUIRE_GRANT_CRYPTO=1
```

5. Optionally configure live grant-status attestation:

```bash
export SCOPE_GRANT_STATUS_URL=https://scope.example/v1/grants/{grant_id}/status
```

When `SCOPE_GRANT_STATUS_URL` is set in strict modes, AKTA fetches the signed
attestation and verifies `attestation_signature` against the trust store.

## Dev / unit tests

Use the clearly marked fixtures under `tests/fixtures/trust_keys/`:

```bash
export AKTA_TRUST_STORE_PATH=tests/fixtures/trust_keys/issuer_registry.yaml
```

Those keys are **test-only**. CI unit profiles may load them; institutional
release profiles must not treat them as production trust roots.

## Fail-closed rules

| Profile | Empty registry | Unknown key_id | Revoked / expired / outside validity |
|---------|----------------|----------------|--------------------------------------|
| `unit` / local | may warn | reject signature | reject |
| `pilot` / `release` / `cross_repo` / `production` | hard fail when crypto required | hard fail | hard fail |

See `akta/trust_store.py` and `akta/scope_grant_verifier.py`.
