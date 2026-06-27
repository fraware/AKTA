# Integrated Weak-Evidence Demo (AKTA v0.2)

One-command pipeline producing the full artifact set for a blocked weak-evidence prioritization request.

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
| `review_trigger.json` | SCOPE-compatible trigger from companion review_required scenario (fixed demo ids) |
| `pf_obligation.json` | PF-Core runtime obligation (schema-validated) |
| `pcs_bundle/` | PCS-compatible bundle with manifest and hash files |

Demo identifiers (`AKTA-DEC-DEMO0001`, `AKTA-SAR-DEMO0001`, timestamp `2026-06-01T12:00:00Z`) are fixed for deterministic hashes.

## Scenario

An analysis assistant (P2) attempts to prioritize a lab queue run based on E2 preliminary signal evidence. AKTA blocks the action and emits constructive `next_admissible_steps`, a PF-Core tool block obligation, and a PCS export bundle.

A companion `review_required` evaluation produces `review_trigger.json` so integrators can validate SCOPE consumption without changing the primary blocked scenario.

Policy and registry hashes are included in every artifact for integrity verification.
