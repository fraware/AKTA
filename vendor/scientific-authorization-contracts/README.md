# Scientific Authorization Contracts

Shared, versioned authorization-envelope and grant schemas for SCOPE and AKTA.

This package is the authoritative source for capability families, operations,
responsibility levels, expiration events, and JSON Schemas. Neither SCOPE nor
AKTA should redefine these contracts independently.

**Package:** `scientific-authorization-contracts==2.1.0`  
Status: beta / reference. Not an institutional certification package.

## Layout

```text
schemas/          JSON Schema artifacts (hashed for CI drift detection)
vocabularies/     Frozen enums and operation partial orders
conformance/      Positive, negative, narrowing, and conflict fixtures
python/           Installable Python package (loader, hashing, envelope, grant)
pyproject.toml    Packaging metadata for pip install from this tree
```

## Install (AKTA / CI)

No public PyPI index yet. Install from the vendor tree before AKTA:

```bash
pip install ./vendor/scientific-authorization-contracts
pip install -e ".[dev]"   # or install the AKTA wheel after contracts
```

Wheel smoke order (clean venv):

```bash
pip install ./vendor/scientific-authorization-contracts
pip install dist/akta_protocol-*.whl
```

## Envelope version

`scientific-authorization-envelope-v2`

## Consumption

Import the installed distribution only:

```python
import scientific_authorization_contracts as contracts

contracts.load_schema("authorization_envelope.v2.schema.json")
contracts.validate_grant(grant)
contracts.envelope_covers(granted, requested)
```

Schema drift between repositories must fail CI.
