# Test-only SCOPE issuer keys

These Ed25519 keys exist solely for unit and integration tests of grant
authentication and grant-status attestation verification.

- **Not** institutional production keys
- **Not** suitable for any live SCOPE-authorized action path
- Private key is unencrypted PEM for local CI determinism only

Generate replacements with:

```bash
python -c "from pathlib import Path; from akta.trust_store import generate_test_keypair; print(generate_test_keypair(Path('tests/fixtures/trust_keys')))"
```

Point tests at `tests/fixtures/trust_keys/issuer_registry.yaml` via
`AKTA_TRUST_STORE_PATH` or an explicit trust_store fixture.
