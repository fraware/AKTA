# AKTA Limitations

## v0.7.1

AKTA v0.7.1 tightens grant-exact re-gating after SCOPE authorization. It explicitly does not:

- Treat a SCOPE grant as a blanket override of AKTA evidence or deployment-profile policy
- Permit tools listed in `prior_review_blocked_tools` even when scope rank would otherwise allow them
- Permit tools outside `prior_review_allowed_tools` when an allowlist is present on the grant
- Fall back to simulated SCOPE mode when `SCOPE_REPO_PATH` or `SCOPE_CLI` is configured

### v0.7.1 grant re-gate limits

- **Grant vs policy**: `evaluate_with_grant()` applies grant metadata then re-evaluates matrix, evidence, and overlay layers. Weak evidence under `P2_analysis_assistant` may still block queue prioritization after a narrow SCOPE grant
- **Tool lists**: `allowed_tools` and `blocked_tools` on SCOPE grants are enforced via `prior_review_*` context metadata; blocked tools take precedence when both lists are present
- **akta-review CLI**: Requires SCOPE CLI with `scope akta review` and `summary.json` conforming to `scope_akta_review_summary.schema.json`
- **Live verify**: `verify_scope_live_chain.py` supports `python-import`, `cli`, and `akta-review` modes; skips when sibling SCOPE repo is absent

## v0.7

AKTA v0.7 adds live SCOPE conformance verification, policy integrity modes, PCS grant hard gates, and adversarial transition reporting (F01–F15). It explicitly does not:

- Certify live SCOPE deployments without running `verify_scope_live_chain.py` against a real sibling repo
- Accept unsigned policy bundles when `AKTA_PRODUCTION_MODE=1` or HMAC-only manifests when `AKTA_REQUIRE_SIGNED_POLICY=1`
- Export PCS bundles with overbroad or shape-invalid SCOPE grants

### v0.7 integration limits

- **Policy integrity**: Three modes (`dev_unsigned`, `deployment_hmac_attested`, `release_ed25519_signed`); production requires explicit env configuration
- **Reconstructable chain**: Canonical artifacts live under `dist/reconstructable_experiment/` after running the demo script; not checked into git by default
- **Holdout private**: Governance doc describes label isolation; holdout scenarios are not published in-repo

## v0.6

AKTA v0.6 closes cross-repo integration gaps and closed-loop review infrastructure. It explicitly does not:

- Certify deployment safety or replace institutional IRB / biosafety review
- Run PF-Core or PCS-Core live validation in default CI (requires sibling repo env vars)
- Support P7 fully autonomous scientific operator (taxonomy-only; runtime refused)
- Guarantee LabTrust-Gym repo availability (minimal compatible JSONL schema provided)

### v0.6 integration limits

- **Cross-repo CI**: Optional jobs activate via repository variables or secrets; default CI remains green without siblings
- **Ed25519 signing**: Requires `pip install akta-protocol[security]` for Ed25519; HMAC remains default for dev manifests
- **Scientific Memory / PCS-Bench**: Import/export shapes are AKTA reference contracts, not full sibling repo implementations
- **Inter-rater labels**: Metadata is advisory for benchmark reporting; gate correctness is still evaluated against expected decisions
- **External PCS-Bench**: Requires sibling checkout at `PCS_BENCH_REPO_PATH`; falls back to in-repo runner when unset or import fails

## v0.5

AKTA v0.5 integrates the full AKTA → SCOPE → PF → PCS artifact chain. It explicitly does not:

- Replace SCOPE reviewer identity verification, signing, or grant lifecycle management
- Certify PCS bundles as safety or regulatory approval (PCS export is artifact packaging only)
- Guarantee live SCOPE repo availability in CI (contract tests use mocks and pinned fixtures)
- Emit global permissions from narrow scoped grants

### v0.5 SCOPE adapter modes

AKTA selects a SCOPE adapter automatically from environment (v0.7.1 adds a fourth mode):

| Mode | Env | Behavior |
|------|-----|----------|
| **simulated** | (default) | Contract simulation only; grants use flat `granted_scope` / `requested_scope` fields and are labeled `adapter_mode: simulated` |
| **python-import** | `SCOPE_REPO_PATH` | Loads sibling SCOPE repo; constructs `ScopeEngine.from_policy_dir(policy/)`; calls v0.5 `create_packet`, `submit_decision`, `issue_grant`. No simulated fallback on import or invocation failure |
| **cli** | `SCOPE_CLI` | Subprocess to real SCOPE v0.5 CLI: `scope packet create --akta-trigger … --akta-record …`, `scope decision submit --packet … --reviewer … --decision …`, `scope grant issue --packet … --decision …` |
| **akta-review-cli** | `SCOPE_CLI` + `SCOPE_CLI_MODE=akta-review` | Unified `scope akta review`; validates `summary.json` against `scope_akta_review_summary.schema.json` (v0.7.1) |

PCS export validates grants using `authorization.approved_scope` (real SCOPE v0.5) or `granted_scope` (simulated). Overbroad grants are rejected; narrowed `active_protocol_update` → `protocol_draft` is accepted.

### v0.5 integration limits

- **SCOPE alignment**: python-import and CLI require SCOPE v0.5 API shapes; simulated mode remains for offline development
- **PCS not safety certification**: Full-chain PCS bundles record provenance; they do not certify deployment safety
- **PF/PCS cross-repo CI**: Contract tests use fixtures; live validation requires sibling checkouts

## v0.4

AKTA v0.4 added operational domain overlays, policy integrity (HMAC manifest), review lifecycle context, structured classification, optional LLM classifier plugin, MCP server, guardrail adapters, PCS-Bench export, and transition runner. It explicitly does not:

- Replace SCOPE grant issuance (SCOPE adapter was simulated or subprocess-only)
- Certify domain overlays as complete safety coverage
- Run PF-Core or PCS-Core live validation without sibling repos

### v0.4 integration limits

- **SCOPE adapter**: Initial `adapters/scope/client.py` with simulated mode and basic subprocess stub (superseded by v0.5 real adapter)
- **Classifier plugin hook**: Registration API exists; default kernel remains deterministic rule-based
- **Domain overlays**: Biology/chemistry/clinical marked experimental, not deployment-ready in production

## v0.3

AKTA v0.3 hardens cross-repo integration with SCOPE, PF-Core, and PCS-Core. It explicitly does not:

- Replace SCOPE review routing, grant lifecycle, or reviewer identity verification
- Guarantee alignment with every SCOPE deployment variant without contract tests
- Run PF-Core or PCS-Core validation in CI when those repositories are unavailable locally
- Load arbitrary classifier plugins without explicit registration (plugin hook is illustrative)
- Certify domain overlays as complete safety coverage (overlays remain illustrative)
- Emit global permissions from narrow scoped grants

### v0.3 integration limits

- **SCOPE alignment**: `requested_scope` uses a fixed enum validated at emission; SCOPE repo code is simulated via `tests/contracts/scope_fixtures.py` when not present locally
- **PF/PCS cross-repo CI**: Contract tests use pinned fixtures mimicking external repo shapes; full cross-repo CI requires sibling checkouts
- **Classifier plugin hook**: Registration API exists; default kernel remains deterministic rule-based
- **Domain overlays**: Hazard triggers and scope overrides are illustrative, not EHS-certified

### Trusted boundary assumptions (v0.3)

- Tool-to-scope mapping in `policy/tool_to_requested_scope.yaml` is reviewed before deployment
- Runtime enforces AKTA decisions and PF obligations before mutating tools
- SCOPE grants are scoped; AKTA re-evaluates or PF blocks out-of-scope tool calls

## v0.2

AKTA v0.2 added per-action evidence rules, consequentiality, SCOPE-compatible review triggers (v0.2 vocabulary), PF obligation export, PCS bundles, and AKTA-Bench 100 scenarios. It does not replace formal authorization or release verification.

## v0.1

AKTA v0.1 is a reference kernel for scientific action admissibility. It explicitly does not:

- Decide scientific truth or correctness
- Replace evidence retrieval or scientific report generation (see VSA)
- Replace formal runtime authorization (see PF-Core)
- Replace release packaging and verification (see PCS-Core)
- Certify autonomous labs or safety compliance
- Replace EHS, IRB, biosafety, chemical safety, clinical review, or legal compliance
- Support fully autonomous scientific operation (P7 is taxonomy-only)
- Guarantee model truthfulness, tool honesty, or reviewer competence

### Trusted boundary assumptions (v0.1)

- Input context is provided honestly or marked uncertain
- Tool registry correctly describes tool effects
- Deployment profile is correctly configured
- Domain overlay is reviewed before deployment
- Runtime harness enforces AKTA decisions

## Non-certification

The AKTA Card describes system deployment characteristics. It is not a safety certification.
