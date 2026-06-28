# PF-Core Bridge (v0.7.1)

PF-Core proves that runtime execution respected AKTA admissibility decisions. AKTA exports machine-readable obligations for PF-Core consumption.

## Division of responsibility

| System | Role |
|--------|------|
| AKTA | Decides scientific action admissibility pre-action |
| PF-Core | Proves runtime honored the decision post-action |

## Obligation export

```bash
akta export pf --record akta_record.json --decision akta_decision.json --out dist/pf_obligations/ --validate
```

Or via Python:

```python
from adapters.pf_core.export_obligation import export_pf_obligation

path = export_pf_obligation(record, "dist/pf_obligations/", decision_id=decision["decision_id"], validate=True)
```

## Obligation schema (v0.2)

```json
{
  "obligation_id": "PF-OBL-AKTA-SAR-...",
  "obligation_type": "tool_block",
  "source": "AKTA",
  "source_record_id": "AKTA-SAR-...",
  "decision_id": "AKTA-DEC-...",
  "blocked_tools": ["lab_scheduler.prioritize"],
  "allowed_tools": [],
  "policy_hash": "sha256:...",
  "tool_registry_hash": "sha256:...",
  "decision": "blocked",
  "enforcement_mode": "hard_block",
  "required_runtime_behavior": {
    "block_execution": true,
    "require_review_before_tool_call": false,
    "require_authorization_before_tool_call": false,
    "blocked_tools": ["lab_scheduler.prioritize"],
    "allowed_tools": [],
    "log_all_tool_calls": false
  },
  "next_admissible_steps": ["..."],
  "required_review_role": null,
  "consequentiality": true,
  "obligation_hash": "sha256:..."
}
```

`obligation_type` mapping:

| Admissibility | obligation_type | enforcement_mode |
|---------------|-----------------|------------------|
| `blocked`, `abstain_insufficient_context` | `tool_block` | `hard_block` |
| `review_required`, `draft_only` | `tool_review` | `review_gate` |
| `authorization_required` | `tool_authorize` | `authorization_gate` |
| `allowed`, `allowed_with_logging` | `tool_allow` | `log_and_allow` |

## Runtime enforcement pattern

```python
obligation = load_pf_obligation(record_id)
if requested_tool in obligation["blocked_tools"]:
    raise ToolBlockedError(obligation)
if obligation["required_runtime_behavior"]["require_review_before_tool_call"]:
  require_valid_review_trigger(requested_tool, obligation)
execute_tool(requested_tool)
```

## Integrity binding

Obligations include `policy_hash`, `tool_registry_hash`, `obligation_hash`, and `source_record_id`. PF-Core should verify:

1. Obligation references a valid AKTA Record
2. Policy hash matches current trusted policy
3. Blocked tool list matches the record decision
4. `consequentiality` aligns with decision for audit trails

## Review triggers and PF-Core

When admissibility is `review_required`, PF-Core should gate tool calls until SCOPE supplies a scoped approval matching `allowed_next_steps`. After grant, runtime should call AKTA `evaluate_with_grant()` before tool dispatch. See [scope_bridge.md](scope_bridge.md) and [review_integration.md](review_integration.md).

## Demo integration

The integrated weak-evidence demo exports a PF obligation blocking `lab_scheduler.prioritize` with v0.2 consequentiality fields.

See [integration_guide.md](integration_guide.md) for the full trust stack.
