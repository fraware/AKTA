# PF-Core Bridge

PF-Core proves that runtime execution respected AKTA admissibility decisions. AKTA exports machine-readable obligations for PF-Core consumption.

## Division of responsibility

| System | Role |
|--------|------|
| AKTA | Decides scientific action admissibility pre-action |
| PF-Core | Proves runtime honored the decision post-action |

## Obligation export

```bash
akta export pf --record akta_record.json --out dist/pf_obligations/
```

Or via Python:

```python
from adapters.pf_core.export_obligation import export_pf_obligation

path = export_pf_obligation(record, "dist/pf_obligations/")
```

## Obligation schema

```json
{
  "obligation_type": "tool_block",
  "source": "AKTA",
  "source_record_id": "AKTA-SAR-...",
  "blocked_tools": ["lab_scheduler.prioritize"],
  "allowed_tools": [],
  "policy_hash": "sha256:...",
  "decision": "blocked",
  "next_admissible_steps": ["..."],
  "required_review_role": null
}
```

`obligation_type` is `tool_block` when admissibility is `blocked` or `abstain_insufficient_context`; otherwise `tool_allow`.

## Runtime enforcement pattern

```python
obligation = load_pf_obligation(record_id)
if requested_tool in obligation["blocked_tools"]:
    raise ToolBlockedError(obligation)
execute_tool(requested_tool)
```

## Integrity binding

Obligations include `policy_hash` and `source_record_id`. PF-Core should verify:

1. Obligation references a valid AKTA Record
2. Policy hash matches current trusted policy
3. Blocked tool list matches the record decision

## Demo integration

The weak-evidence demo exports a PF obligation blocking `lab_scheduler.prioritize` and documents that the runtime trace shows the tool was not called.

See [integration_guide.md](integration_guide.md) for the full trust stack.
