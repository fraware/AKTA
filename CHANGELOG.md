# Changelog

All notable changes to AKTA are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.5.0] - 2026-06-28

### Added

- Real SCOPE adapter modes: `simulated`, `python-import` (`SCOPE_REPO_PATH`), `cli` (`SCOPE_CLI`) with `scope packet create`, `scope decision submit`, `scope grant issue`
- PCS v0.5 full-chain export: `scope_decision.json`, `scope_grant.json`, `pf_obligation.json`, per-file `file_hashes`, tamper validation (`validate_pcs_bundle`)
- Production policy integrity: `AKTA_PRODUCTION_MODE=1` requires manifest, deployment HMAC key; rejects dev key
- LLM classifier trust boundary: tool registry always overrides LLM; `llm_advisory` metadata in decisions; `docs/classifier_trust_boundary.md`
- Overlay governance tiers: `core_reference`, `experimental_domain_overlay`, `expert_reviewed_domain_overlay`, `institutional_deployment_overlay`
- Policy file versioning: `policy_file_version` per YAML; `policy_bundle_version` in decision provenance
- Contract tests: `test_scope_import_mode_contract.py`, `test_real_scope_cli_contract.py`, `test_pcs_full_chain_tamper.py`

### Changed

- Policy bundle version `akta-core-v0.5`; package version `0.5.0`
- PCS manifest `schema_version` → `akta-record-v0.5`
- SCOPE adapter mode labels: `simulated` | `python-import` | `cli` (replaces `subprocess`)
- Biology/chemistry/clinical overlays marked `experimental_domain_overlay` (not deployment-ready in production)

## [0.4.0] - 2026-06-28

### Added

- Operational domain overlays: `biology_v0.yaml`, `chemistry_v0.yaml`, `clinical_v0.yaml` (replace placeholders)
- Policy integrity: `policy/policy_manifest.yaml` with HMAC-SHA256 verification (`akta/policy_integrity.py`)
- Review lifecycle: `akta/review_context.py` (F12 disclaimer, F14 stale review, prior record influence)
- Review decision import stub: `schemas/review_decision.schema.json`, `akta/review_decision.py`
- Structured classification from `context.structured_action` / `context.tool_payload`
- Optional LLM classifier plugin (`AKTA_LLM_CLASSIFIER` + `OPENAI_API_KEY`, fail-closed without key)
- SCOPE adapter: `adapters/scope/client.py` (simulated or subprocess via `SCOPE_CLI`)
- MCP stdio server: `adapters/mcp/server.py` (`akta_evaluate`, `akta_export`)
- Guardrail adapters: `adapters/guardrails/openai_adapter.py`, `anthropic_adapter.py`
- PCS-Bench export: `adapters/pcs_bench/export_suite.py`
- Transition runner: `evals/transition_runner.py` (SCOPE grant → re-gate)
- Oracle-independent scenarios: `scenarios/oracle_independent.jsonl` (10 hand-written labels)
- Tool registry expanded to 27 tools; `scientific_memory.import` → A8 with correct mutability
- REST OpenAPI spec at `adapters/generic_rest/openapi.yaml`; API version v0.3

### Changed

- Policy version `akta-core-v0.4`; package version `0.4.0`
- PCS manifest `schema_version` → `akta-record-v0.3`
- PF obligation export adds `decision_reason_hash`, `scope_grant_ref`, `review_trigger_id`, `expires_at`
- LangGraph middleware: `AKTAReviewRequired` for review_required; draft_only allows non-mutating tools only
- `allowed_log_nonconseq` respects consequentiality; legacy evidence matrix fail-closed for consequential actions
- Review triggers emit `expires_at`; demo weak-evidence exports review trigger only when primary path requires review
- Archived `scenarios/public_40.jsonl` (superseded by `public_100.jsonl`)

### Removed

- Placeholder overlays (`biology_placeholder.yaml`, etc.)

## [0.3.0] - 2026-06-28

### Added

- SCOPE v0.3 review trigger schema: required `requested_scope`, optional `review_route`, ID aliases (`akta_decision_id`, `akta_record_id`)
- `policy/tool_to_requested_scope.yaml` tool-to-scope mapping for A5–A10 review-relevant tools
- `akta/scope_mapping.py` resolver with valid SCOPE enum enforcement
- AKTA x SCOPE integrated protocol-drift demo (`examples/integrated_protocol_drift/`, `make demo-akta-scope-protocol-drift`)
- Cross-repo contract tests: `tests/contracts/` with SCOPE fixture simulator, PF obligation, PCS manifest fixtures
- Scenario eval checks for `requested_scope`, severity, failure_mode tags; `requested_scope_accuracy` metric
- Domain overlay v0.2 expansions: A5/A8/A9/A10 minimum evidence, reviewer roles, hazard triggers, scope overrides

### Changed

- Policy version bumped to `akta-core-v0.3`; package version `0.3.0`
- Review trigger version `0.3`; deprecated v0.2 `review_scope` vocabulary removed from emission
- `expected_decisions.jsonl` enriched with `requested_scope`, severity, and failure_mode metadata
- Documentation refresh: `docs/limitations.md` v0.2/v0.3 sections, `docs/scope_bridge.md` v0.3 fields

## [0.2.0] - 2026-06-27

### Added

- Per-action evidence-to-action rules (`policy/evidence_to_action_rules.yaml`) replacing rank-only loopholes
- Consequentiality classification with `consequentiality` and `consequentiality_reason` on decisions
- Conditional alias resolution: `allowed_log_or_review`, `draft_only_or_review_required`, `draft_validation_only`
- SCOPE-compatible review triggers with full bridge fields and schema validation
- CLI: `akta review-trigger export`, `akta export pcs --validate`, `akta export pf --validate`
- Rich classifier output: alternates, matched_source, uncertainty_flags, classifier_mode
- Low-confidence fail-closed for mutating/external tools
- PF-Core obligation schema and contract (`schemas/pf_core_obligation.schema.json`)
- PCS artifact schema and validated export (`schemas/pcs_akta_artifact.schema.json`)
- AKTA-Bench expanded to 100 public scenarios with per-failure-class metrics
- Integrated weak-evidence demo (`examples/integrated_weak_evidence/`, `make demo-akta-weak-evidence`)
- 30+ new tests covering evidence rules, consequentiality, review triggers, classifier, PF/PCS contracts

### Changed

- Evidence matrix layer renamed to `evidence_rules` in evaluation layers
- Review triggers emitted for both `review_required` and `authorization_required`
- PCS manifest schema version bumped to `akta-record-v0.2`
- `public_30_strong_evidence_draft` expected decision: `draft_only` (draft tool, non-mutating)

### Security

- Per-action evidence constraints prevent rank-based A5 escalation under weak evidence

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
