# VSA Import

Verified Science Agent (VSA) reports provide evidence context for AKTA admissibility decisions. AKTA imports VSA output but does not blindly trust it.

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

## Warnings and human review

VSA warnings are preserved in `context.metadata.vsa_warnings`. VSA human review flags are stored but do not automatically override AKTA policy — AKTA applies its own admissibility matrix.

## Example fixtures

See `examples/weak_evidence/vsa_report.json`, `vsa_input.json`, and `vsa_imported_context.json`.
