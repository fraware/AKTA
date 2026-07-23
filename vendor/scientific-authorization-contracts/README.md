# Scientific Authorization Contracts

Shared, versioned authorization-envelope and grant schemas for SCOPE and AKTA.

This package is the authoritative source for capability families, operations,
responsibility levels, expiration events, and JSON Schemas. Neither SCOPE nor
AKTA should redefine these contracts independently.

Status: beta / reference. Not an institutional certification package.

## Layout

```text
schemas/          JSON Schema artifacts (hashed for CI drift detection)
vocabularies/     Frozen enums and operation partial orders
conformance/      Positive, negative, narrowing, and conflict fixtures
python/           Optional loader helpers for Python consumers
```

## Envelope version

`scientific-authorization-envelope-v2`

## Consumption

SCOPE loads schemas and vocabularies from this directory at runtime and embeds
`authorization_schema_version` plus `authorization_schema_hash` on decisions
and grants. AKTA should pin the same directory (or published artifact hash).

Schema drift between repositories must fail CI.
