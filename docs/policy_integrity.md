# Policy Integrity

AKTA policy integrity ensures admissibility decisions are tied to a verifiable, tamper-evident policy bundle.

## Policy bundle

The bundle in `policy/` includes:

- Action ontology and responsibility levels
- Evidence, validation, and verification statuses
- Deployment profiles
- Admissibility matrix
- Evidence-to-action matrix
- Tool registry

## Hashing

`PolicyBundle.policy_hash` covers all policy YAML files. `tool_registry_hash` covers the tool registry separately. Hashes use SHA-256 prefixed with `sha256:`.

Every AKTA Decision and Record includes:

```json
{
  "policy_version": "akta-core-v0.5",
  "policy_file_versions": { "action_ontology.yaml": "action_ontology-v0.5", "...": "..." },
  "policy_hash": "sha256:...",
  "tool_registry_hash": "sha256:..."
}
```

## Verification workflow

```python
from akta.policy import PolicyBundle

bundle = PolicyBundle.from_dir("policy/")
assert decision["policy_hash"] == bundle.policy_hash
assert decision["tool_registry_hash"] == bundle.tool_registry_hash
```

Records additionally verify `record_hash` over all fields except the hash itself.

## Tampering detection (F8)

If policy files are modified without updating references:

1. Decision `policy_hash` will not match loaded bundle
2. PF-Core obligations become invalid
3. PCS manifest hash files will not match record provenance

v0.7 defines three integrity modes (exact `integrity_mode` vocabulary):

| Mode | When | Env |
|------|------|-----|
| `dev_unsigned` | No manifest or unsigned manifest outside production | default dev |
| `deployment_hmac_attested` | HMAC-SHA256 manifest with deployment secret | `AKTA_VERIFY_POLICY=1` + `AKTA_POLICY_HMAC_KEY` |
| `release_ed25519_signed` | Ed25519 manifest verified against `policy/release_keys.yaml` | `AKTA_REQUIRE_SIGNED_POLICY=1` or release registry match |

| Env | Behavior |
|-----|----------|
| `AKTA_PRODUCTION_MODE=1` | Requires signed manifest; rejects dev HMAC key |
| `AKTA_VERIFY_POLICY=1` | Requires manifest; accepts HMAC deployment attestation |
| `AKTA_REQUIRE_SIGNED_POLICY=1` | Requires Ed25519 release signature (rejects HMAC-only) |

v0.6 adds Ed25519 signing alongside HMAC:

| Algorithm | Sign | Verify |
|-----------|------|--------|
| HMAC-SHA256 | `AKTA_POLICY_HMAC_KEY` (default dev key in regenerate script) | `AKTA_POLICY_HMAC_KEY` |
| Ed25519 | `AKTA_POLICY_SIGNING_KEY` (32-byte hex or base64) | `AKTA_POLICY_PUBLIC_KEY` or manifest `public_keys` |

```bash
pip install akta-protocol[security]
export AKTA_POLICY_SIGNING_KEY=<32-byte-hex-private-key>
python scripts/regenerate_policy_manifest.py --algorithm Ed25519
export AKTA_REQUIRE_SIGNED_POLICY=1
export AKTA_POLICY_PUBLIC_KEY=<base64-public-key>
```

Key rotation: include retired public keys in manifest `public_keys` or set `AKTA_POLICY_PREVIOUS_PUBLIC_KEYS` when regenerating.

v0.5 separates dev and production verification:

| Mode | Env | Behavior |
|------|-----|----------|
| Dev (default) | — | Verify hashes when manifest exists; dev HMAC key OK with warning |
| Production | `AKTA_PRODUCTION_MODE=1` or `AKTA_VERIFY_POLICY=1` | Requires manifest + deployment `AKTA_POLICY_HMAC_KEY`; rejects dev key |

Regenerate manifest after policy edits: `python scripts/regenerate_policy_manifest.py`

v0.4 included optional HMAC-SHA256 manifest verification via `policy/policy_manifest.yaml`.

## Tool registry integrity

Unknown tools with `mutates_state: true` or `external_effect: true` default to abstain. Registry poisoning is mitigated by:

- Hash in every decision
- Fail-closed unknown tool handling
- Schema validation of registry YAML

## Overlay integrity

Domain overlays have independent `overlay_hash` values. Changing an overlay without re-evaluation produces detectable hash mismatches.

## CI validation

The CI pipeline validates:

- All JSON schemas
- Policy bundle loads without error
- Scenario eval passes with pinned expected decisions
- Invalid cases fail as expected

See [SECURITY.md](../SECURITY.md) for vulnerability reporting.
