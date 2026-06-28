# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.5.x   | Yes       |
| 0.4.x   | Yes       |
| 0.3.x   | Yes       |

## Reporting a vulnerability

Report security issues privately to the repository maintainers via GitHub Security Advisories on [fraware/AKTA](https://github.com/fraware/AKTA).

Do not open public issues for undisclosed vulnerabilities.

## Security model (v0.5)

AKTA is part of the agent supply chain. Threats include policy tampering, fake AKTA Records, domain overlay manipulation, tool registry poisoning, review trigger spoofing, stale review reuse, unknown tool confusion, and downgrade attacks.

### Dev vs production policy integrity

| Mode | Environment variables | Manifest | HMAC key | Overlay policy |
|------|----------------------|----------|----------|----------------|
| Dev (default) | none required | optional | dev key accepted with warning | experimental overlays allowed |
| Verify | `AKTA_VERIFY_POLICY=1` | required | deployment key required | experimental overlays allowed |
| Production | `AKTA_PRODUCTION_MODE=1` | required | deployment key required; dev key rejected | experimental overlays refused |

Regenerate manifest after policy edits: `python scripts/regenerate_policy_manifest.py`

See [docs/policy_integrity.md](docs/policy_integrity.md).

### v0.5 controls

- JSON schema validation on all artifacts
- Canonical SHA-256 hashing of policy bundle, domain overlays, and tool registry
- Dev vs production policy integrity (`AKTA_PRODUCTION_MODE=1`, `AKTA_VERIFY_POLICY=1`)
- Production requires deployment-specific `AKTA_POLICY_HMAC_KEY`; rejects in-repo dev key
- PCS bundle per-file hash manifest with tamper detection
- Overlay governance tiers; production refuses experimental high-risk overlays
- LLM classifier advisory-only; tool registry overrides LLM output
- Policy hash, domain overlay hash, and tool registry hash in every decision
- Record hash on every AKTA Record
- Review context enforcement (F14 stale review, F12 disclaimer boundary)
- Unknown mutating tools blocked by default (abstain_insufficient_context)

### v0.4 controls (retained)

- JSON schema validation on all artifacts
- Canonical SHA-256 hashing of policy bundle, domain overlays, and tool registry
- Optional HMAC-SHA256 policy manifest verification (`policy/policy_manifest.yaml`, `AKTA_VERIFY_POLICY=1`)
- Policy hash, domain overlay hash, and tool registry hash in every decision
- Record hash on every AKTA Record
- Review context enforcement (F14 stale review, F12 disclaimer boundary)
- Unknown mutating tools blocked by default (abstain_insufficient_context)
- Explicit version fields on policy and schemas

### Out of scope for v0.5

- Ed25519 signed policy releases (HMAC deployment key supported; public-key verification stub only)
- Live SCOPE/PF/PCS runtime enforcement (delegated to external repos; AKTA adapters simulate or bridge)
- Model truthfulness guarantees

See [docs/threat_model.md](docs/threat_model.md) for the full threat model.
