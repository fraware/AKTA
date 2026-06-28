# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.4.x   | Yes       |
| 0.3.x   | Yes       |

## Reporting a vulnerability

Report security issues privately to the repository maintainers via GitHub Security Advisories on [fraware/AKTA](https://github.com/fraware/AKTA).

Do not open public issues for undisclosed vulnerabilities.

## Security model (v0.4)

AKTA is part of the agent supply chain. Threats include policy tampering, fake AKTA Records, domain overlay manipulation, tool registry poisoning, review trigger spoofing, stale review reuse, unknown tool confusion, and downgrade attacks.

### v0.4 controls

- JSON schema validation on all artifacts
- Canonical SHA-256 hashing of policy bundle, domain overlays, and tool registry
- Optional HMAC-SHA256 policy manifest verification (`policy/policy_manifest.yaml`, `AKTA_VERIFY_POLICY=1`)
- Policy hash, domain overlay hash, and tool registry hash in every decision
- Record hash on every AKTA Record
- Review context enforcement (F14 stale review, F12 disclaimer boundary)
- Unknown mutating tools blocked by default (abstain_insufficient_context)
- Explicit version fields on policy and schemas

### Out of scope for v0.4

- Ed25519 signed policy releases in production (HMAC dev key only in-repo)
- Live SCOPE/PF/PCS runtime enforcement (delegated to external repos)
- Model truthfulness guarantees

See [docs/threat_model.md](docs/threat_model.md) for the full threat model.
