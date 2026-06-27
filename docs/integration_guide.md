# AKTA Integration Guide

AKTA integrates with adjacent systems in the AI-for-science trust stack.

## Verified Science Agent (VSA)

- **VSA answers:** Is this scientific claim/report grounded in evidence?
- **AKTA answers:** Is this AI-generated output admissible to become scientific action?

Import VSA reports via `adapters/vsa/import_report.py` to populate evidence context. AKTA does not blindly trust VSA outputs.

## Provability Fabric Core (PF-Core)

- **AKTA decides** scientific admissibility
- **PF-Core proves** the runtime respected the AKTA decision

Export obligations: `akta export pf --record akta_record.json --out dist/pf_obligations/`

## PCS-Core

AKTA Records export as PCS-compatible artifact bundles:

```bash
akta export pcs --record akta_record.json --out dist/pcs_artifacts/
```

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
```
