# AKTA Threat Model (v0.4)

AKTA sits in the agent supply chain between model output and scientific action. This document describes threats, v0.4 controls, residual risk, and out-of-scope items.

## Trust boundaries

| Boundary | Trusted side | Untrusted side |
|----------|--------------|----------------|
| Policy bundle | Maintainer-signed manifest (optional HMAC) | Runtime tampering |
| Tool registry | Hashed YAML in policy bundle | Ad-hoc tool injection |
| Domain overlays | Hashed overlay files | Overlay substitution |
| Review context | SCOPE grant metadata bound to trigger | Stale or laundered review |
| Classifier | Deterministic path + optional plugins | Model hallucination, NL ambiguity |

## Threat catalog

| Threat | v0.4 control | Residual risk |
|--------|--------------|---------------|
| Policy tampering | `policy_hash` on every decision/record; optional HMAC manifest verification (`AKTA_VERIFY_POLICY=1`) | Dev HMAC key in-repo is not production-grade |
| Fake AKTA Records | Record hash, JSON schema validation | Forged records outside AKTA export path |
| Domain overlay manipulation | `domain_overlay_hash` in provenance | Wrong overlay selected by integrator |
| Tool registry poisoning | `tool_registry_hash`; unknown mutating tools → abstain | Custom registry not pinned at deploy time |
| Review trigger spoofing | Trigger bound to `decision_id` / `record_id`; hash fields | External SCOPE not validating bindings |
| Stale review reuse (F14) | `review_context.py` blocks expired or narrow grants | Metadata omitted by caller |
| Review laundering (F6/F12) | Disclaimer metadata does not bypass mutating tools | Prompt-only disclaimers without metadata |
| Unknown tool confusion | D6 abstain; block mutating tools by default | Misclassified non-mutating custom tools |
| Downgrade attacks | Strictest-decision composition across layers | Caller ignores blocked decision |
| Schema version confusion | Explicit version fields on policy, records, PCS manifest | Mixed-version consumers |
| NL classification bypass | Structured action priority; negation guard; fail-closed low confidence | Adversarial phrasing edge cases |
| LLM classifier abuse | Opt-in only; requires API key; structured JSON schema; returns None on failure | Compromised API credentials |
| Handoff escalation (F7) | Handoff chain monotonicity detection | Incomplete handoff metadata |

## v0.4 additions over v0.1

- Operational domain overlays (biology, chemistry, clinical) with hazard triggers
- Review lifecycle enforcement (`prior_review_expired`, `prior_akta_records`)
- Per-action evidence rules (legacy rank loophole closed for consequential actions)
- SCOPE adapter with simulated and subprocess modes
- MCP stdio server and guardrail adapters for runtime integration
- Oracle-independent eval scenarios (labels not derived from gate oracle)
- Transition runner for SCOPE grant → re-gate flows

## Out of scope (v0.4)

- Ed25519 signed policy releases in production (HMAC dev key only in-repo)
- Live SCOPE/PF/PCS runtime enforcement (delegated to sibling repos)
- Model prompt injection defense and truthfulness guarantees
- Log integrity and audit trail storage
- Physical lab safety certification

## Verification

- `pytest tests/test_policy_integrity_v04.py` — manifest tampering detection
- `pytest tests/test_invalid_cases.py` — F8 policy tampering fixtures
- `pytest tests/test_oracle_independent.py` — hand-written expected labels
- `make ci` — full regression including scenario eval and integration demos

See [SECURITY.md](../SECURITY.md) for vulnerability reporting and [policy_integrity.md](policy_integrity.md) for hash verification setup.
