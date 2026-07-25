# Stack Profile

Machine-readable declaration of compatible VSA / AKTA / SCOPE / PF-Core / PCS / Scientific-Memory versions (AS-02). Package baseline: **1.2.0**.

## Role

| Artifact | Role |
|----------|------|
| `stack_profile.json` | Portable declaration of intended stack versions |
| `policy/release_pins.yaml` | Institutional pin source of truth |
| `policy/scope_compatibility_manifest.json` | SCOPE/contracts compatibility |
| `policy/shared_contracts_pin.json` | Contracts wheel/manifest digests |

Unsupported combinations fail closed. Incomplete institutional pins and placeholder release signers remain fail-closed under institutional / `bounded_execution` profiles. Validation does not imply sibling systems are live or certified.
## Schema

See [`schemas/stack_profile.schema.json`](../schemas/stack_profile.schema.json).

## CLI

```bash
akta validate-stack-profile stack_profile.json
```

Exit non-zero when the profile is unsupported, missing required components, or disagrees with release pins / package `__version__`.

## Python

```python
from akta.stack_profile import validate_stack_profile

result = validate_stack_profile("stack_profile.json")
assert result["ok"]  # or inspect result["errors"]
```

## Fixtures

`tests/fixtures/as02/` — valid institutional, unsupported combo, missing components.
