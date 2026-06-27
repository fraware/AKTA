# Changelog

All notable changes to AKTA are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-06-27

### Added

- Reference AKTA Gate kernel with deterministic rule-based classification and strictest-decision composition
- Policy bundle: action ontology, responsibility levels, evidence states, validation statuses, verification statuses, deployment profiles, admissibility matrix, evidence-to-action matrix, default tool registry
- JSON schemas for decisions, records, context, cards, tool registry, domain overlays, review triggers, multi-agent handoffs
- CLI: `gate`, `record`, `card validate`, `eval`, `export pcs`, `export pf`
- Python API: `AKTAGate`, `AKTAContext`, `AKTADecision`, `AKTARecord`
- Canonical five scenarios, public 40-scenario benchmark, invalid-case fixtures, and scenario evaluator with metrics (accuracy, overreach, overblocking, record completeness, helpful boundedness)
- Adapters: VSA report import, PF-Core obligation export, PCS artifact export, generic REST server (`akta-rest`), MCP wrapper, LangGraph middleware
- AKTA Skill package with examples and validation tests
- Domain overlays: materials, computational science, generic lab (operational); biology, chemistry, clinical (non-operational placeholders)
- Integrated weak-evidence demo (`scripts/demo_weak_evidence.py`, `make demo-weak-evidence`)
- Documentation: scientific action admissibility, authority transfer, limitations, integration guide, AKTA Card guide, threat model, trusted boundary, policy integrity
- CI workflow: pytest, schema validation, canonical/public evals, invalid fixtures, integrated demo

### Security

- Policy, tool registry, and domain overlay hashes in every decision
- Record hash on every AKTA Record
- Unknown mutating tools fail closed (`abstain_insufficient_context`)
- Schema validation enforced in tests and CI

### Non-goals (v0.1)

- P7 fully autonomous scientific operator not supported
- No operational bio/chem protocol examples
- Rule-based classification only (no LLM classifier)
- Signed policies and review infrastructure implementation deferred to later releases
