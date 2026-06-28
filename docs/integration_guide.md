# AKTA Integration Guide (v0.4)

AKTA integrates with adjacent systems in the AI-for-science trust stack.

## v0.4 integration additions

| Component | Path | Purpose |
|-----------|------|---------|
| SCOPE adapter | `adapters/scope/client.py` | Simulated or subprocess review flow |
| MCP stdio server | `adapters/mcp/server.py` | `akta_evaluate`, `akta_export` over JSON-RPC |
| Guardrail adapters | `adapters/guardrails/` | OpenAI / Anthropic tool-call checks |
| Transition runner | `evals/transition_runner.py` | SCOPE grant → re-gate verification |
| Oracle-independent eval | `evals/run_oracle_independent.py` | Hand-written expected labels |
| Domain overlays | `overlays/biology_v0.yaml`, `chemistry_v0.yaml`, `clinical_v0.yaml` | Hazard triggers and scope overrides |
| Policy integrity | `akta/policy_integrity.py` | HMAC manifest verification |
| PCS-Bench export | `adapters/pcs_bench/export_suite.py` | Benchmark suite for PCS-Core |

```bash
# Oracle-independent eval
python evals/run_oracle_independent.py --out evals/reports/oracle_independent.json

# MCP server (stdio)
python -m adapters.mcp.server

# REST API v0.4
akta-rest --host 127.0.0.1 --port 8765
```

Cross-repo contract tests: [tests/contracts/README.md](../tests/contracts/README.md).

## Verified Science Agent (VSA)

- **VSA answers:** Is this scientific claim/report grounded in evidence?
- **AKTA answers:** Is this AI-generated output admissible to become scientific action?

Import VSA reports via `adapters/vsa/import_report.py` to populate evidence context. AKTA does not blindly trust VSA outputs.

## Provability Fabric Core (PF-Core)

- **AKTA decides** scientific admissibility
- **PF-Core proves** the runtime respected the AKTA decision

Export obligations:

```bash
akta export pf --record akta_record.json --decision akta_decision.json --out dist/pf_obligations/ --validate
```

See [pf_core_bridge.md](pf_core_bridge.md) for obligation schema and enforcement patterns.

## PCS-Core

AKTA Records export as PCS-compatible artifact bundles:

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

## v0.2 policy features

| Feature | Integration point |
|---------|-------------------|
| Per-action evidence rules | `policy/evidence_to_action_rules.yaml` |
| Consequentiality | Decision `consequentiality` / `consequentiality_reason` |
| Rich classifier | Decision `classification` audit block |
| PF obligation v0.2 | `enforcement_mode`, `required_runtime_behavior` |
| PCS bundle v0.4 | `schema_version: akta-record-v0.4` |

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

## Integrated demo

```bash
python scripts/demo_integrated_weak_evidence.py
```

Produces blocked weak-evidence artifacts plus a review-trigger companion example in `examples/integrated_weak_evidence/`.
