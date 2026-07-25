# AKTA Threat Model (v1.2 + AS hardening)

AKTA sits in the agent supply chain between model output and scientific action. This document describes threats, controls by release, residual risk, and out-of-scope items. Package version: **1.2.0**. AKTA is not a safety certification.

## AS workstream non-claims (threat posture)

The Admissibility-Stack hardening (AS-00–08) adds digest bindings, stack profiles, decision basis, uniform failures, pilot modes, outcome refs, and reconstruction CLI. It does **not** claim:

- Defense against model prompt injection or model truthfulness
- That pilot outcome linkage improves scientific quality or efficacy
- That shadow evaluations may authorize execution
- That incomplete institutional pins (placeholder signers, missing siblings) are acceptable under `bounded_execution` / institutional release
- Replacement of SCOPE/PF/PCS as systems of record for identity, runtime proof, or release packaging

Residual risk for forged records outside the AKTA export path, misconfigured production env, and incomplete sibling checkouts remains as below.

## AS controls (1.2.x)

- Binding digests on decisions/records; reconstruction CLI verifies release bundles
- Stack profile validation against institutional pins (fail closed on placeholder signers / missing siblings when required)
- Pilot-mode allowlists and shadow isolation (`operational_influence: false`)
- Uniform failure surfaces additive to local reason codes
- Append-only outcome refs; metrics exclude raw evidence text

These controls harden reconstructability and pilot boundaries. They do not upgrade `runtime_observed` adapter results into cryptographic or institutional guarantees.

## Trust boundaries

| Boundary | Trusted side | Untrusted side |
|----------|--------------|----------------|
| Policy bundle | Signed or HMAC-attested manifest | Runtime tampering |
| Tool registry | Hashed YAML in policy bundle | Ad-hoc tool injection |
| Domain overlays | Hashed overlay files | Overlay substitution |
| Review context | SCOPE grant metadata bound to trigger | Stale or laundered review |
| Classifier | Deterministic path + optional advisory LLM | Model hallucination, NL ambiguity |
| SCOPE grant | Scoped authorization after human review | Overbroad or expired grants |

## Threat catalog

| Threat | Control | Residual risk |
|--------|---------|---------------|
| Policy tampering (F8) | `policy_hash`; three integrity modes; Ed25519 release signing | Misconfigured production env |
| Fake AKTA Records | Record hash, JSON schema validation | Forged records outside AKTA export path |
| Domain overlay manipulation | `domain_overlay_hash` in provenance | Wrong overlay selected by integrator |
| Tool registry poisoning | `tool_registry_hash`; unknown mutating tools → abstain | Custom registry not pinned at deploy time |
| Review trigger spoofing | Trigger bound to decision/record IDs; hash fields | External SCOPE not validating bindings |
| Stale review reuse (F14) | `review_loop.py`; expired/narrow grant blocks | Metadata omitted by caller |
| Grant override after review | `evaluate_with_grant()` re-gates evidence/profile; `prior_review_*` tool lists | Caller skips re-gate |
| Review laundering (F6/F12) | Disclaimer metadata does not bypass mutating tools | Prompt-only disclaimers without metadata |
| Unknown tool confusion (F13) | Abstain; block mutating tools by default | Misclassified non-mutating custom tools |
| Downgrade attacks | Strictest-decision composition across layers | Caller ignores blocked decision |
| Schema version confusion | Explicit version fields on policy, records, PCS manifest | Mixed-version consumers |
| NL classification bypass | Structured action priority; negation guard; fail-closed low confidence | Adversarial phrasing edge cases |
| LLM classifier abuse | Opt-in only; tool registry overrides LLM; fail-closed without key | Compromised API credentials |
| Handoff escalation (F7) | Handoff chain monotonicity detection | Incomplete handoff metadata |
| Overbroad SCOPE grant | PCS export rejects; grant validation fixtures | SCOPE misconfiguration upstream |
| Simulated SCOPE fallback | Live verify fails when real env configured but simulation used | Missing sibling repo in dev |

## v0.7.1 controls

- Grant-exact re-gate: `prior_review_allowed_tools` and `prior_review_blocked_tools`
- SCOPE grants do not auto-override weak-evidence or deployment-profile blocks
- SCOPE `akta-review-cli` mode with `summary.json` schema validation
- Reconstructable demo post-grant assertions (Cases A/B/C)

## v0.7 controls

- Live SCOPE chain verification (`scripts/verify_scope_live_chain.py`)
- Three policy integrity modes: `dev_unsigned`, `deployment_hmac_attested`, `release_ed25519_signed`
- Closed-loop `review_loop` with grant allowlist and blocked_tools preservation
- Adversarial transition reporting F01–F15
- PCS grant hard gates (real + simulated fixtures)

## v0.5–v0.6 controls (retained)

- Dev vs production policy integrity (`AKTA_PRODUCTION_MODE=1`, `AKTA_VERIFY_POLICY=1`)
- PCS per-file `file_hashes` with tamper detection
- Overlay governance tiers; production refuses experimental overlays
- LLM classifier advisory-only; tool registry overrides LLM
- Review context enforcement (F14 stale review, F12 disclaimer boundary)
- REST optional API key auth and rate limiting (v0.6)
- Ed25519 signed policy releases (v0.6+)

## Out of scope

- Live SCOPE/PF/PCS runtime enforcement in default CI (delegated to sibling repos; AKTA adapters bridge or simulate)
- Model prompt injection defense and truthfulness guarantees
- Log integrity and audit trail storage
- Physical lab safety certification or regulatory approval
- P7 fully autonomous scientific operator runtime (permanently unsupported)
- Learning policy from pilot outcome metrics / RL loops (AS non-claim)
- Institution-wide scientific efficacy scoring from pilot metrics (AS non-claim)

## Verification

- `make ci` — full regression including scenario eval, adversarial transitions, and integration demos
- `pytest tests/test_as01_bindings.py tests/test_as02_stack_profile.py tests/test_as03_decision_basis.py tests/test_as04_uniform_failures.py tests/test_as05_pilot_modes.py tests/test_as06_bindings_chain.py tests/test_as07_outcome_metrics.py tests/test_as08_reconstruct.py` — AS suite
- `python scripts/verify_scope_live_chain.py` — live SCOPE conformance (optional sibling repo)
- `pytest tests/test_policy_signing_modes.py` — integrity mode enforcement
- `pytest tests/test_invalid_cases.py` — F8 policy tampering fixtures
- `pytest tests/test_evaluate_with_grant.py` — grant re-gate semantics

See [SECURITY.md](../SECURITY.md), [policy_integrity.md](policy_integrity.md), [RELEASE.md](RELEASE.md), and [adr/0001-admissibility-boundary.md](adr/0001-admissibility-boundary.md).
