# AKTA v0.3 Integration Summary

AKTA v0.3 hardens the bridge to SCOPE, PF-Core, and PCS-Core. This document summarizes how the reference kernel connects to downstream systems and where authority boundaries sit.

## System roles

| System | Responsibility |
|--------|----------------|
| AKTA | Pre-action admissibility, classification, evidence gating, review trigger emission |
| SCOPE | Review routing, scoped grant lifecycle, reviewer workflow |
| PF-Core | Runtime enforcement of AKTA decisions and PF obligations |
| PCS-Core | Packaging AKTA records, decisions, review triggers, and SCOPE packets |

## v0.3 review trigger contract

When admissibility is `review_required` or `authorization_required`, AKTA emits a review trigger with:

- **Required:** `requested_scope` (SCOPE approval scope enum)
- **Optional:** `review_route` (human/process routing hint)
- **ID aliases:** `akta_decision_id` / `decision_id`, `akta_record_id` / `source_record_id`
- **Version:** `review_trigger_version = "0.3"`

Tool-to-scope mapping lives in `policy/tool_to_requested_scope.yaml`. AKTA never emits values outside the SCOPE enum.

The SCOPE simulator in `akta/scope_contract.py` accepts v0.3 triggers and falls back to legacy `review_scope` vocabulary for compatibility testing only. New emissions use `requested_scope` exclusively.

## Canonical integration demo

**Use `examples/integrated_protocol_drift/`** for the full AKTA → SCOPE → PF → PCS chain:

```bash
python scripts/demo_akta_scope_protocol_drift.py
# or: make demo-akta-scope-protocol-drift
```

This demo runs in one command:

1. Active protocol update → `review_required` with `requested_scope=active_protocol_update`
2. SCOPE review packet assembly (`scope_review_packet.json`)
3. Narrow grant: protocol owner approves `protocol_draft` only
4. Draft follow-up allowed; active update and robot submit remain blocked
5. PF obligation and PCS bundle (including `review_trigger.json` and `scope_review_packet.json`)

## Weak-evidence demo (AKTA-only)

`examples/integrated_weak_evidence/` demonstrates AKTA gate → record → PF → PCS for weak-evidence blocking. It does **not** simulate SCOPE routing or grants. For SCOPE integration, use the protocol-drift demo above.

## Contract testing

| Test suite | Purpose |
|------------|---------|
| `tests/contracts/test_scope_trigger_contract.py` | Trigger-only, record-only, trigger+record SCOPE packets |
| `tests/contracts/test_pf_obligation_contract.py` | PF obligation shape vs pinned fixtures |
| `tests/contracts/test_pcs_manifest_contract.py` | PCS manifest includes v0.3 review trigger |
| `tests/test_tool_to_scope.py` | A5–A10 tool-to-scope mapping on live gate |

When the SCOPE repository is not checked out locally, `tests/contracts/scope_fixtures.py` re-exports the simulator from `akta.scope_contract`.

## Authority-transfer boundary

AKTA assigns `requested_scope`; SCOPE grants approval scope. A narrow grant (e.g. `protocol_draft` when `active_protocol_update` was requested) must not authorize active mutation or robot execution. PF-Core enforces runtime obligations; PCS packages artifacts for bench and memory workflows.

Neither AKTA nor SCOPE alone authorizes global permission.

## Related documentation

- [scope_bridge.md](scope_bridge.md) — SCOPE field consumption and anti-patterns
- [review_integration.md](review_integration.md) — Review trigger semantics
- [limitations.md](limitations.md) — v0.3 integration limits
- [pf_core_bridge.md](pf_core_bridge.md) — Runtime enforcement
- [pcs_export.md](pcs_export.md) — PCS bundle layout
