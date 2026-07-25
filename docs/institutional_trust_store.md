# Institutional trust store

> **Current status:** Package **1.2.0**. Prefer [deployment_reference.md](deployment_reference.md), [policy_integrity.md](policy_integrity.md), and [RELEASE.md](RELEASE.md). Registries below remain the grant/status/manifest trust domains.

AKTA authenticates SCOPE artifacts against **separate** public-key registries:

| Registry | Artifact | Env override |
|----------|----------|--------------|
| `policy/scope_grant_issuer_registry.yaml` | grant signatures | `AKTA_GRANT_ISSUER_REGISTRY` / `AKTA_TRUST_STORE_PATH` |
| `policy/scope_status_attestation_registry.yaml` | grant-status attestations | `AKTA_STATUS_ATTESTATION_REGISTRY` |
| `policy/scope_policy_manifest_signer_registry.yaml` | authorization manifests (WS5) | `AKTA_MANIFEST_SIGNER_REGISTRY` |
| `policy/reviewer_decision_registry.yaml` | local reviewer decisions only | (explicit load; never grant-issuer) |

Strict modes (`pilot` \| `release` \| `cross_repo` \| `production`) **require real
cryptography** and fail closed when the grant-issuer registry is empty, missing,
or contains only revoked/expired keys.

Beta designation: reference trust-binding mechanism, not an institutional
certification claim.

## Entry schema

Each registry entry supports:

| Field | Required | Notes |
|-------|----------|-------|
| `key_id` | yes | Stable key identifier (also used as map key) |
| `status` | yes | `active` \| `revoked` \| `expired` \| `pending` |
| `algorithm` | yes | `Ed25519` only in v1 |
| public material | one of | `public_key_ref`, `public_key_pem`, or `public_key_file` |
| `authorized_artifact_types` | recommended | Multi-role only via explicit list |
| `valid_from` / `valid_until` | recommended | ISO-8601; outside window → reject |
| `issuer_identity` | optional | Human/org label; not a secret |
| `tenant` / `institution` | optional | Tenancy binding |
| `replacement_key_id` | optional | Rotation pointer |
| `revocation_reason` | optional | When status is revoked |

**Reviewer keys are never auto-imported as grant issuers.** SCOPE sibling
`reviewer_key_registry.yaml` is not merged into the grant-issuer store.

## How institutions deploy

1. Generate or obtain an Ed25519 **issuer** keypair offline (HSM/KMS preferred).
2. Export **public** PEM only into `scope_grant_issuer_registry.yaml` (and
   separately into status/manifest registries as appropriate).
3. Point AKTA at those files:

```bash
export AKTA_GRANT_ISSUER_REGISTRY=/etc/akta/scope_grant_issuer_registry.yaml
export AKTA_STATUS_ATTESTATION_REGISTRY=/etc/akta/scope_status_attestation_registry.yaml
# optional alias still accepted:
export AKTA_TRUST_STORE_PATH=/etc/akta/scope_grant_issuer_registry.yaml
```

4. Enable a strict grant mode (crypto is automatic for all strict modes):

```bash
export AKTA_GRANT_MODE=production
# or: pilot | release | cross_repo
```

5. Optionally configure live grant-status attestation:

```bash
export SCOPE_GRANT_STATUS_URL=https://scope.example/v1/grants/{grant_id}/status
```

## Dev / unit tests

Use fixtures under `tests/fixtures/trust_keys/`:

```bash
export AKTA_TRUST_STORE_PATH=tests/fixtures/trust_keys/issuer_registry.yaml
```

Those keys are **test-only**.

## Fail-closed rules

| Profile | Empty grant-issuer registry | Unknown key_id | Revoked / expired / outside validity |
|---------|-----------------------------|----------------|--------------------------------------|
| `unit` / local | may warn | reject when store provided | reject |
| `pilot` / `release` / `cross_repo` / `production` | hard fail | hard fail | hard fail |

See `akta/trust_store.py` and `akta/scope_grant_verifier.py`.
