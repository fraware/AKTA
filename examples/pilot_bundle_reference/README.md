# Pilot bundle reference manifest (hashes only)

This directory documents a reproducible pilot bundle without committing binary artifacts.
Generate the live bundle at release time:

```bash
SCOPE_REPO_PATH=../SCOPE make demo-pilot-bundle
```

## Expected artifacts

| Slot | File |
|------|------|
| 00 | vsa_report.json |
| 01 | akta_decision_pre_grant.json |
| 02 | akta_record.json |
| 03 | review_trigger.json |
| 04 | scope_review_summary.json |
| 05–07 | scope_packet/decision/grant |
| 08 | akta_decision_after_grant.json |
| 09–10 | pf_obligation / pf_trace_certificate |
| 11 | pcs_bundle/ |
| 12–14 | memory import, pcs_bench report, quality_report |

## Checksums

Run after generation:

```bash
python scripts/generate_pilot_bundle_reference.py
```

See `manifest_hashes.json` for pinned SHA-256 checksums from the reference v1.0 chain.

## reconstruction_report excerpt

The pilot bundle includes `reconstruction_report.md` documenting:

- SCOPE fixture `contract_version`
- Adapter mode (must not be `simulated` for release claims)
- PCS manifest hash linkage to AKTA record
