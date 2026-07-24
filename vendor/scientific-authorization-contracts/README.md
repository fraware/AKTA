# Scientific Authorization Contracts

Shared, versioned authorization-envelope schemas, vocabularies, and algebra for
SCOPE and AKTA.

Package: `scientific-authorization-contracts==2.1.0`

This distribution is the authoritative source for capability families, operations,
responsibility levels, expiration events, JSON Schemas, and envelope algebra.
Neither SCOPE nor AKTA should redefine these contracts independently.

## Install (local monorepo)

```bash
pip install -e ./scientific-authorization-contracts
pip install -e ".[dev]"
```

Or build wheels and install with find-links:

```bash
python -m build scientific-authorization-contracts
python -m build .
pip install --find-links dist "scientific-authorization-contracts==2.1.0" "scope-protocol==2.1.0"
```

Declared SCOPE dependency pin: `scientific-authorization-contracts==2.1.0`.
AKTA must pin the same release version and wheel hash.

## Layout

```text
src/scientific_authorization_contracts/
  schemas/          JSON Schema artifacts (hashed for CI drift detection)
  vocabularies/     Frozen enums and operation partial orders
  conformance/      Positive, negative, narrowing, and conflict fixtures
  envelope.py       Authorization envelope model + algebra
  hashing.py        Canonical JSON hashing helpers
```

## Envelope version

`scientific-authorization-envelope-v2`

## Public API

```python
from scientific_authorization_contracts import (
    AuthorizationEnvelope,
    envelope_contains,
    envelope_intersection,
)
```

Schema drift between repositories must fail CI.
