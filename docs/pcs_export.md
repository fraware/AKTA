# PCS Export (v0.5)

AKTA Records export as PCS-compatible artifact bundles for packaging, benchmarking, and scientific memory import. PCS export records provenance; it is not a safety certification.

## Export command

```bash
akta export pcs --record akta_record.json --decision akta_decision.json --out dist/pcs_bundle/ --validate
```

The `--validate` flag validates the manifest against `schemas/pcs_akta_artifact.schema.json` and verifies per-file hashes.

REST API:

```bash
POST /v0/export/pcs
{"record": { ... akta record object ... }}
```

## Bundle contents

### Core files (always present)

| File | Purpose |
|------|---------|
| `akta_record.json` | Full AKTA Record |
| `akta_decision.json` | Decision summary with consequentiality and classification fields |
| `policy_hash.txt` | Policy integrity reference |
| `domain_overlay_hash.txt` | Overlay integrity reference |
| `tool_registry_hash.txt` | Registry integrity reference |
| `manifest.json` | Bundle index, schema version, and `file_hashes` |

### Optional artifacts (included when data is present)

| File | Purpose |
|------|---------|
| `review_trigger.json` | SCOPE-consumed review trigger |
| `scope_review_packet.json` | SCOPE packet (trigger + record) |
| `scope_decision.json` | SCOPE reviewer decision |
| `scope_grant.json` | Scoped authorization grant |
| `vsa_report.json` | Imported VSA ScientificReport |
| `pf_obligation.json` | PF-Core runtime obligation |

## Manifest (v0.5)

```json
{
  "artifact_type": "akta_scientific_action_record",
  "schema_version": "akta-record-v0.5",
  "integrity_mode": "deployment_hmac_attested",
  "record_hash": "sha256:...",
  "policy_hash": "sha256:...",
  "decision_id": "AKTA-DEC-...",
  "files": ["akta_record.json", "akta_decision.json", "..."],
  "file_hashes": {
    "akta_record.json": "sha256:...",
    "akta_decision.json": "sha256:..."
  }
}
```

`file_hashes` is required in v0.5. Tamper detection recomputes hashes and rejects mismatches.

## SCOPE grant validation

When `scope_grant.json` is included, PCS export validates:

- Real SCOPE v0.5+ grants via `authorization.approved_scope`
- Simulated grants via `granted_scope` (labeled `adapter_mode: simulated`)
- Rejects overbroad grants; accepts narrowed grants (e.g. `active_protocol_update` → `protocol_draft`)

Fixtures: `tests/fixtures/scope_grants/`.

## Use cases

1. **Demo packaging** — combine VSA report, AKTA Record, PF obligation, review trigger, SCOPE grant, and manifest
2. **PCS-Bench validation** — verify good and bad artifact bundles
3. **Scientific Memory import** — bounded results enter long-term project memory
4. **SCOPE ingestion** — review triggers packaged for review orchestration (see [scope_bridge.md](scope_bridge.md))

## Validation

AKTA v0.5 ensures:

- Record passes `akta_record.schema.json`
- Manifest passes `pcs_akta_artifact.schema.json` when `--validate` is used
- All `file_hashes` match on-disk content
- Manifest file list matches exported files
- `schema_version` is `akta-record-v0.5`
- Overbroad SCOPE grants are rejected at export time

PCS-Bench (external) validates bundle completeness against sibling repo rules.

## Python API

```python
from adapters.pcs.export_artifact import export_pcs_bundle

export_pcs_bundle(
    record,
    "dist/pcs_bundle/",
    decision=decision_dict,
    scope_grant=grant_dict,  # optional; validated when present
    validate=True,
)
```

See `scripts/demo_integrated_weak_evidence.py`, `scripts/demo_akta_scope_protocol_drift.py`, and `scripts/demo_reconstructable_experiment.py` for end-to-end PCS export.
