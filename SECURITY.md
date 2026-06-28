# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.7.x   | Yes       |
| 0.6.x   | Yes       |
| 0.5.x   | Yes       |
| 0.4.x   | Yes       |
| 0.3.x   | Yes       |

## Reporting a vulnerability

Report security issues privately to the repository maintainers via GitHub Security Advisories on [fraware/AKTA](https://github.com/fraware/AKTA).

Do not open public issues for undisclosed vulnerabilities.

## Security model

AKTA is part of the agent supply chain. Threats include policy tampering, fake AKTA Records, domain overlay manipulation, tool registry poisoning, review trigger spoofing, stale review reuse, grant override after SCOPE authorization, unknown tool confusion, and downgrade attacks.

See [docs/threat_model.md](docs/threat_model.md).

### Policy integrity modes (v0.7)

| Mode | Environment variables | Manifest | Verification |
|------|----------------------|----------|--------------|
| `dev_unsigned` | none (default dev) | optional | Hash verification when manifest present |
| `deployment_hmac_attested` | `AKTA_VERIFY_POLICY=1` + `AKTA_POLICY_HMAC_KEY` | required | HMAC-SHA256 deployment attestation |
| `release_ed25519_signed` | `AKTA_REQUIRE_SIGNED_POLICY=1` | required | Ed25519 against `policy/release_keys.yaml` |

| Env | Behavior |
|-----|----------|
| `AKTA_PRODUCTION_MODE=1` | Requires signed manifest; rejects dev HMAC key; refuses experimental overlays |
| `AKTA_VERIFY_POLICY=1` | Requires manifest; accepts HMAC deployment attestation |
| `AKTA_REQUIRE_SIGNED_POLICY=1` | Requires Ed25519 release signature (rejects HMAC-only) |

Regenerate manifest after policy edits: `python scripts/regenerate_policy_manifest.py`

See [docs/policy_integrity.md](docs/policy_integrity.md).

### v0.7.1 controls

- Grant-exact re-gate: `prior_review_allowed_tools` and `prior_review_blocked_tools` enforced in `evaluate_with_grant()`
- SCOPE grants do not auto-override weak-evidence or deployment-profile blocks
- SCOPE `akta-review-cli` mode with `summary.json` schema validation
- Live SCOPE verify supports python-import, cli, and akta-review; fails on simulated fallback

### v0.7 controls

- Live SCOPE chain verification (`scripts/verify_scope_live_chain.py`)
- PCS export rejects overbroad SCOPE grants
- Closed-loop grant re-gate via `akta/review_loop.py`
- Adversarial transition reporting F01–F15

### v0.6 controls

- Ed25519 signed policy manifests; HMAC retained for deployment attestation
- Key rotation via manifest `public_keys` list and `AKTA_POLICY_PREVIOUS_PUBLIC_KEYS` at sign time
- REST API optional key auth (`AKTA_REST_API_KEY`) and rate limiting
- Mandatory tool declaration fail-closed for unregistered mutating tools

### v0.5 controls (retained)

- JSON schema validation on all artifacts
- Canonical SHA-256 hashing of policy bundle, domain overlays, and tool registry
- PCS bundle per-file hash manifest with tamper detection
- Overlay governance tiers; production refuses experimental high-risk overlays
- LLM classifier advisory-only; tool registry overrides LLM output
- Policy hash, domain overlay hash, and tool registry hash in every decision
- Record hash on every AKTA Record
- Review context enforcement (F14 stale review, F12 disclaimer boundary)
- Unknown mutating tools blocked by default (`abstain_insufficient_context`)

### Out of scope

- Live SCOPE/PF/PCS runtime enforcement in default CI (delegated to external repos)
- Model truthfulness guarantees
- P7 fully autonomous scientific operator runtime
- Safety or regulatory certification
