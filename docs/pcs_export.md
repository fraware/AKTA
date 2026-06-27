# PCS Export

AKTA Records export as PCS-compatible artifact bundles for packaging, benchmarking, and scientific memory import.

## Export command

```bash
akta export pcs --record akta_record.json --out dist/pcs_artifacts/
```

REST API:

```bash
POST /v0/export/pcs
{"record": { ... akta record object ... }}
```

## Bundle contents

| File | Purpose |
|------|---------|
| `akta_record.json` | Full AKTA Record |
| `akta_decision.json` | Decision summary |
| `policy_hash.txt` | Policy integrity reference |
| `domain_overlay_hash.txt` | Overlay integrity reference |
| `tool_registry_hash.txt` | Registry integrity reference |
| `review_trigger.json` | Present when review required |
| `manifest.json` | Bundle index and schema version |

## Manifest example

```json
{
  "artifact_type": "akta_scientific_action_record",
  "schema_version": "akta-record-v0.1",
  "record_hash": "sha256:...",
  "policy_hash": "sha256:...",
  "files": ["akta_record.json", "akta_decision.json", "..."]
}
```

## Use cases

1. **Demo packaging** — combine VSA report, AKTA Record, PF obligation, and manifest
2. **PCS-Bench validation** — verify good and bad artifact bundles
3. **Scientific Memory import** — bounded results enter long-term project memory

## Validation

PCS-Bench (external) validates bundle completeness. AKTA v0.1 ensures:

- Record passes `akta_record.schema.json`
- All hash files match record provenance
- Manifest file list matches exported files

## Python API

```python
from adapters.pcs.export_artifact import export_pcs_bundle

export_pcs_bundle(record, "dist/pcs_artifacts/")
```

See the weak-evidence demo (`scripts/demo_weak_evidence.py`) for end-to-end PCS export.
