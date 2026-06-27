# PCS Export (v0.2)

AKTA Records export as PCS-compatible artifact bundles for packaging, benchmarking, and scientific memory import.

## Export command

```bash
akta export pcs --record akta_record.json --decision akta_decision.json --out dist/pcs_bundle/ --validate
```

The `--validate` flag validates the manifest against `schemas/pcs_akta_artifact.schema.json`.

REST API:

```bash
POST /v0/export/pcs
{"record": { ... akta record object ... }}
```

## Bundle contents

| File | Purpose |
|------|---------|
| `akta_record.json` | Full AKTA Record |
| `akta_decision.json` | Decision summary with v0.2 consequentiality fields |
| `policy_hash.txt` | Policy integrity reference |
| `domain_overlay_hash.txt` | Overlay integrity reference |
| `tool_registry_hash.txt` | Registry integrity reference |
| `review_trigger.json` | Present when record includes review trigger |
| `manifest.json` | Bundle index and schema version |

## Manifest example (v0.2)

```json
{
  "artifact_type": "akta_scientific_action_record",
  "schema_version": "akta-record-v0.2",
  "record_hash": "sha256:...",
  "policy_hash": "sha256:...",
  "decision_id": "AKTA-DEC-...",
  "files": ["akta_record.json", "akta_decision.json", "review_trigger.json", "..."]
}
```

When `review_trigger` is present on the record, it is exported as `review_trigger.json` and listed in `manifest.files`.

## Use cases

1. **Demo packaging** — combine VSA report, AKTA Record, PF obligation, review trigger, and manifest
2. **PCS-Bench validation** — verify good and bad artifact bundles
3. **Scientific Memory import** — bounded results enter long-term project memory
4. **SCOPE ingestion** — review triggers packaged for review orchestration (see [scope_bridge.md](scope_bridge.md))

## Validation

PCS-Bench (external) validates bundle completeness. AKTA v0.2 ensures:

- Record passes `akta_record.schema.json`
- Manifest passes `pcs_akta_artifact.schema.json` when `--validate` is used
- All hash files match record provenance
- Manifest file list matches exported files
- `schema_version` is `akta-record-v0.2`

## Python API

```python
from adapters.pcs.export_artifact import export_pcs_bundle

export_pcs_bundle(record, "dist/pcs_bundle/", decision=decision_dict, validate=True)
```

See `scripts/demo_integrated_weak_evidence.py` for end-to-end PCS export with review trigger companion artifacts.
