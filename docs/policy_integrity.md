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
  "policy_version": "akta-core-v0.1",
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

v0.1 does not include signed policy releases. Integrators should pin policy versions and verify hashes at startup.

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
