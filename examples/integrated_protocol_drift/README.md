# Integrated Protocol Drift Demo (AKTA v0.7.1 x SCOPE)

This example demonstrates the authority-transfer boundary between AKTA pre-action admissibility and SCOPE scoped human approval.

## Flow

1. An agent requests `protocol_editor.update_active_protocol`.
2. AKTA returns `review_required` with `requested_scope=active_protocol_update`.
3. AKTA emits a v0.3 review trigger (`review_trigger.json`) and SCOPE packet (`scope_review_packet.json`).
4. A protocol owner grants **only** `protocol_draft` scope (`scope_narrow_grant.json`).
5. `protocol_editor.draft_change` is admissible in `draft_only` mode; active update and `robot_queue.submit` remain blocked.
6. PF-Core obligation and PCS bundle capture the blocked active-update record for runtime enforcement and packaging.

## Authority boundary

AKTA decides whether a transition is admissible and which SCOPE `requested_scope` applies.
SCOPE decides who reviews and what scope is granted. PF-Core enforces the resulting runtime obligation. PCS packages artifacts for bench and memory workflows.

Neither AKTA nor SCOPE alone authorizes global permission. A narrow `protocol_draft` grant must not unlock active protocol mutation or robot execution. AKTA does not broaden SCOPE grants; SCOPE does not override AKTA evidence or profile policy by default.

## Regenerate

```bash
python scripts/demo_akta_scope_protocol_drift.py
# or: make demo-akta-scope-protocol-drift
```

With live SCOPE sibling:

```bash
export SCOPE_REPO_PATH=/path/to/SCOPE
python scripts/demo_akta_scope_protocol_drift.py
# Output must show adapter_mode=python-import or cli, never simulated
```

## Artifacts

| File | Role |
|------|------|
| `akta_decision_active_update.json` | Active protocol update decision |
| `akta_record_active_update.json` | Record with embedded review trigger |
| `review_trigger.json` | SCOPE-consumed trigger (`requested_scope`, ID aliases) |
| `scope_review_packet.json` | Trigger + record packet for SCOPE routing |
| `scope_narrow_grant.json` | Simulated narrow grant (draft only) |
| `akta_decision_draft_only.json` | Permitted draft-only follow-up |
| `pf_obligation.json` | PF-Core runtime obligation |
| `pcs_bundle/` | PCS v0.5 export including review trigger and scope artifacts |
