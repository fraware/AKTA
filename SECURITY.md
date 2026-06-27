# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a vulnerability

Report security issues privately to the repository maintainers via GitHub Security Advisories on [fraware/AKTA](https://github.com/fraware/AKTA).

Do not open public issues for undisclosed vulnerabilities.

## Security model (v0.1)

AKTA is part of the agent supply chain. Threats include policy tampering, fake AKTA Records, domain overlay manipulation, tool registry poisoning, review trigger spoofing, unknown tool confusion, and downgrade attacks.

### v0.1 controls

- JSON schema validation on all artifacts
- Canonical SHA-256 hashing of policy bundle, domain overlays, and tool registry
- Policy hash, domain overlay hash, and tool registry hash in every decision
- Record hash on every AKTA Record
- Unknown mutating tools blocked by default (D6 abstain_insufficient_context)
- Explicit version fields on policy and schemas

### Out of scope for v0.1

- Signed policy releases (planned)
- Runtime enforcement (delegated to PF-Core and harness)
- Model truthfulness guarantees

See [docs/threat_model.md](docs/threat_model.md) for the full threat model.
