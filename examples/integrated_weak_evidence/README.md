# Integrated Weak-Evidence Demo (AKTA v0.3)

AKTA gate → record → PF-Core → PCS pipeline for weak-evidence blocking.
This demo does **not** simulate SCOPE review routing or scoped grants.

For the canonical AKTA x SCOPE integration demo, see
[`examples/integrated_protocol_drift/`](../integrated_protocol_drift/README.md).

## Run

```bash
make demo-akta-weak-evidence
# or
python scripts/demo_integrated_weak_evidence.py
```

## Artifacts produced

| File | Description |
|------|-------------|
| `akta_decision.json` | Gate decision with consequentiality and classification detail |
| `akta_record.json` | Schema-validated scientific action record |
| `review_trigger.json` | v0.3 trigger from companion review_required scenario (trigger export only; no SCOPE packet) |
| `pf_obligation.json` | PF-Core runtime obligation (schema-validated) |
| `pcs_bundle/` | PCS-compatible bundle with manifest and hash files |

Demo identifiers (`AKTA-DEC-DEMO0001`, `AKTA-SAR-DEMO0001`, timestamp `2026-06-01T12:00:00Z`) are fixed for deterministic hashes.

## Scenario

An analysis assistant (P2) attempts to prioritize a lab queue run based on E2 preliminary signal evidence. AKTA blocks the action and emits constructive `next_admissible_steps`, a PF-Core tool block obligation, and a PCS export bundle.

A companion `review_required` evaluation produces `review_trigger.json` for trigger-schema validation. For the full AKTA→SCOPE→PF→PCS chain, use `examples/integrated_protocol_drift/`.

Policy and registry hashes are included in every artifact for integrity verification.
