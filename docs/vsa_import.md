# VSA Import

> **Current status:** Package **1.2.0**. Prefer [integration_guide.md](integration_guide.md) and [RELEASE.md](RELEASE.md). Import binds evidence context only — it does not certify claim truth or authorize action.

Verified Science Agent (VSA) reports provide evidence context for AKTA admissibility decisions. AKTA imports VSA output but does not blindly trust it. A successful import binds evidence context; it does not certify claim truth or authorize action by itself.

## Division of responsibility

| System | Question |
|--------|----------|
| VSA | Is this scientific claim/report grounded in evidence? |
| AKTA | Is this AI output admissible to become scientific action? |

## Import adapter

```python
from adapters.vsa.import_report import import_vsa_report

context_fields = import_vsa_report(vsa_report)
# Returns: evidence_state, validation_status, vsa_report_ref, metadata
```

## Evidence strength mapping

| VSA strength | AKTA evidence state |
|--------------|---------------------|
| none | E0_no_evidence |
| anecdotal | E1_anecdotal_or_informal_observation |
| preliminary / weak | E2_preliminary_signal |
| noisy / conflicting | E3_noisy_or_conflicting_evidence |
| consistent | E4_internally_consistent_evidence |
| replicated | E5_internally_replicated_evidence |
| independent | E6_independently_reproduced_evidence |
| validated | E7_deployment_validated_evidence |

## Validation status mapping

Derived from `validation_results` in the VSA report:

- `independently_replicated` → V5
- `internally_replicated` → V4
- `preliminary_experimental` → V3
- `simulation_supported` → V2
- `literature_supported` → V1
- default → V0_unvalidated

## Integration pattern

```python
vsa_ctx = import_vsa_report(vsa_report)
context = {**base_context, **vsa_ctx}

decision = gate.evaluate(
    ai_output=ai_output,
    requested_tool=tool,
    context=AKTAContext.from_dict(context),
    ...
)
```

Scenario evaluation supports inline `vsa_report` fields in JSONL scenarios.

## AS-01: decision-time VSA bundle binding

Prefer a normalized `vsa_bundle` over a loose `vsa_report` when both are present:

```python
from adapters.vsa.import_report import import_vsa_report, normalize_vsa_bundle, resolve_vsa_source

ctx = import_vsa_report(report)  # attaches vsa_bundle + bundle_digest
# or
bundle = normalize_vsa_bundle(report, declared_digest="sha256:...")
```

Fail-closed rules:

| Condition | Behavior |
|-----------|----------|
| Declared digest ≠ recomputed digest | `VSAImportError` (`vsa_bundle_digest_mismatch`) |
| Empty / non-object report | `missing_digest` |
| Multiple `evidence_refs` / reports without `selected_vsa_digest` | `ambiguous_evidence_refs` |
| Both `vsa_bundle` and `vsa_report` | Prefer `vsa_bundle` |

Migration: callers may keep supplying `vsa_report`; the import adapter and gate resolve to `vsa_bundle` and bind `vsa_decision_time_bundle_digest` on the decision `bindings` object.

## Warnings and human review

VSA warnings are preserved in `context.metadata.vsa_warnings`. VSA human review flags are stored but do not automatically override AKTA policy — AKTA applies its own admissibility matrix.

## Example fixtures

See `examples/weak_evidence/vsa_report.json`, `vsa_input.json`, and `vsa_imported_context.json`.
AS-01 fixtures: `tests/fixtures/as01/`.
