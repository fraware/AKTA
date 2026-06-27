# AKTA Threat Model (v0.1)

AKTA is part of the agent supply chain. Threats include:

| Threat | v0.1 control |
|--------|--------------|
| Policy tampering | Policy hash in every decision and record |
| Fake AKTA Records | Record hash, schema validation |
| Domain overlay manipulation | Overlay hash in decisions and records |
| Tool registry poisoning | Registry hash; unknown mutating tools blocked |
| Review trigger spoofing | Review triggers bound to decision/record IDs |
| Unknown tool confusion | D6 abstain; block mutating tools by default |
| Downgrade attacks | Strictest-decision composition |
| Schema version confusion | Explicit version fields |

## Out of scope (v0.1)

- Signed policy releases
- Runtime enforcement (delegated to PF-Core)
- Model prompt injection defense
- Log integrity guarantees

See [SECURITY.md](../SECURITY.md) for vulnerability reporting.
