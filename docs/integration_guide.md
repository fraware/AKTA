# AKTA Integration Guide (v0.7.1)

AKTA integrates with adjacent systems in the AI-for-science trust stack. This guide summarizes reference-implementation integration points by release. AKTA is not a safety certification.

## v0.7.1 integration additions

| Component | Path | Purpose |
|-----------|------|---------|
| Grant-exact re-gate | `akta/review_context.py`, `akta/review_loop.py` | `prior_review_allowed_tools` / `prior_review_blocked_tools` after SCOPE grant |
| SCOPE akta-review CLI | `adapters/scope/client.py` | `SCOPE_CLI_MODE=akta-review` → `scope akta review` + `summary.json` validation |
| Reconstructable demo Cases A/B/C | `scripts/demo_reconstructable_experiment.py` | Post-grant admissibility assertions (grant does not override evidence/profile) |
| Review summary schema | `schemas/scope_akta_review_summary.schema.json` | Validates SCOPE akta-review CLI output |

```bash
# Grant-exact re-gate after SCOPE authorization
from akta import AKTAGate
gate = AKTAGate.from_policy_dir("policy/")
decision = gate.evaluate_with_grant(ai_output=..., requested_tool=..., scope_grant=grant, ...)

# SCOPE akta-review CLI mode
export SCOPE_CLI=scope
export SCOPE_CLI_MODE=akta-review
python scripts/verify_scope_live_chain.py --mode akta-review

python scripts/demo_reconstructable_experiment.py
```

See [scope_live_conformance.md](scope_live_conformance.md) and [limitations.md](limitations.md).

## v0.7 integration additions

| Component | Path | Purpose |
|-----------|------|---------|
| Live SCOPE verify | `scripts/verify_scope_live_chain.py` | python-import, cli, akta-review modes; fails on simulated fallback |
| Policy integrity modes | `akta/policy_signing.py` | `dev_unsigned`, `deployment_hmac_attested`, `release_ed25519_signed` |
| Closed-loop review | `akta/review_loop.py` | Grant allowlist, protocol/evidence invalidation, blocked_tools preservation |
| Adversarial F01–F15 | `evals/adversarial_transitions.py` | Per-class transition reporting |
| Holdout governance | `evals/run_holdout_eval.py` | Private holdout slice for release acceptance |

```bash
export AKTA_REQUIRE_SIGNED_POLICY=1   # Ed25519 release mode
python evals/adversarial_transitions.py --out evals/reports/adversarial_transitions.json
make eval-holdout
```

## v0.6 integration additions

| Component | Path | Purpose |
|-----------|------|---------|
| Cross-repo CI | `.github/CROSS_REPO_CI.md` | Optional PF/PCS/SCOPE/PCS-Bench jobs |
| Closed-loop review | `akta/review_decision.py` | Human review packet export/import |
| Ed25519 signing | `akta/policy_signing.py` | Release authenticity via `policy/release_keys.yaml` |
| VSA rich report | `adapters/vsa/import_report.py` | PCS `vsa_report.json` artifact |
| Scientific Memory / PCS-Bench | `adapters/scientific_memory/`, `adapters/pcs_bench/` | Import/export reference contracts |
| REST auth | `adapters/generic_rest/server.py` | `AKTA_REST_API_KEY`, rate limiting |

## v0.5 integration additions

| Component | Path | Purpose |
|-----------|------|---------|
| SCOPE adapter | `adapters/scope/client.py` | Simulated, python-import (`SCOPE_REPO_PATH`), or CLI (`SCOPE_CLI`) |
| SCOPE engine protocol | `adapters/scope/engine_protocol.py` | Expected methods for python-import mode |
| PCS v0.5 full chain | `adapters/pcs/export_artifact.py` | Per-file `file_hashes`, tamper validation |
| Production policy integrity | `akta/policy_integrity.py` | Dev vs production HMAC; manifest required in production |
| Overlay governance | `akta/overlays.py` | Tiers; production refuses experimental overlays |
| LLM trust boundary | `docs/classifier_trust_boundary.md` | Tool registry overrides LLM; advisory metadata only |

```bash
# Production mode
export AKTA_PRODUCTION_MODE=1
export AKTA_POLICY_HMAC_KEY="<deployment-secret>"
python scripts/regenerate_policy_manifest.py  # after policy edits

# SCOPE modes
export SCOPE_REPO_PATH=/path/to/SCOPE   # python-import
export SCOPE_CLI=scope                  # CLI subprocess
python scripts/demo_akta_scope_protocol_drift.py

# PCS full-chain validate
akta export pcs --record akta_record.json --decision akta_decision.json --out pcs_bundle/ --validate
```

## v0.4 integration additions (historical)

| Component | Path | Purpose |
|-----------|------|---------|
| MCP stdio server | `adapters/mcp/server.py` | `akta_evaluate`, `akta_export` over JSON-RPC |
| Guardrail adapters | `adapters/guardrails/` | OpenAI / Anthropic tool-call checks |
| Transition runner | `evals/transition_runner.py` | SCOPE grant → re-gate verification |
| Oracle-independent eval | `evals/run_oracle_independent.py` | Hand-written expected labels |
| Domain overlays | `overlays/biology_v0.yaml`, etc. | Hazard triggers and scope overrides |

Cross-repo contract tests: [tests/contracts/README.md](../tests/contracts/README.md).

## Verified Science Agent (VSA)

- **VSA answers:** Is this scientific claim/report grounded in evidence?
- **AKTA answers:** Is this AI-generated output admissible to become scientific action?

Import VSA reports via `adapters/vsa/import_report.py` to populate evidence context. AKTA does not blindly trust VSA outputs.

## Provability Fabric Core (PF-Core)

- **AKTA decides** scientific admissibility
- **PF-Core proves** the runtime respected the AKTA decision

```bash
akta export pf --record akta_record.json --decision akta_decision.json --out dist/pf_obligations/ --validate
```

See [pf_core_bridge.md](pf_core_bridge.md).

## PCS-Core

```bash
akta export pcs --record akta_record.json --decision akta_decision.json --out dist/pcs_bundle/ --validate
```

When review is required, the bundle includes `review_trigger.json`. See [pcs_export.md](pcs_export.md).

## SCOPE review orchestration

AKTA emits SCOPE-compatible review triggers on `review_required` and `authorization_required`:

```bash
akta review-trigger export --decision akta_decision.json --out review_trigger.json
```

See [scope_bridge.md](scope_bridge.md) and [review_integration.md](review_integration.md).

## Python API

```python
from akta import AKTAGate, AKTAContext

gate = AKTAGate.from_policy_dir("policy/")
decision = gate.evaluate(
    ai_output={"summary": "..."},
    requested_tool="lab_scheduler.prioritize",
    requested_action="prioritize_next_run",
    context=AKTAContext.from_file("context.json"),
    deployment_profile="P2_analysis_assistant",
    domain_overlay="generic_lab_v0",
)
record = decision.to_record()
```

## CLI

```bash
akta gate --output ai_output.json --tool lab_scheduler.prioritize --profile P2_analysis_assistant --context context.json --out decision.json
akta record --decision decision.json --out record.json
akta eval --scenarios scenarios/canonical_5.jsonl --expected scenarios/expected_decisions.jsonl
akta eval --scenarios scenarios/public_100.jsonl --expected scenarios/expected_decisions.jsonl
akta export pcs --record record.json --decision decision.json --out pcs_bundle/ --validate
akta export pf --record record.json --decision decision.json --out pf_obligations/ --validate
akta review-trigger export --decision decision.json --out review_trigger.json
```

## Integrated demos

```bash
python scripts/demo_integrated_weak_evidence.py          # AKTA → PF → PCS (no SCOPE)
python scripts/demo_akta_scope_protocol_drift.py         # AKTA → SCOPE → PF → PCS
python scripts/demo_reconstructable_experiment.py        # Full reconstructable chain
```

Public release checklist: [RELEASE.md](RELEASE.md).
