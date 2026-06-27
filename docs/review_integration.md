# Review Integration

AKTA emits typed review triggers when admissibility is `review_required` or `authorization_required`.

## Review trigger schema

Review triggers conform to `schemas/review_trigger.schema.json` and include:

| Field | Purpose |
|-------|---------|
| `review_trigger_id` | Unique trigger identifier |
| `source_record_id` | Bound AKTA Record |
| `required_review_role` | Who must review |
| `review_scope` | What the review covers |
| `review_artifacts_required` | Evidence packet contents |
| `approval_effect` | Scoped permission, not global |
| `default_expiration` | Typically `single_run` |

## Default review roles

| Action type | Default role |
|-------------|--------------|
| A5 protocol modification | protocol_owner |
| A6 experimental planning | domain_scientist |
| A7 queue prioritization | domain_scientist |
| A10 publication claim | domain_scientist |

Domain overlays may override roles (e.g., `compute_lead` for computational science).

## Integration workflow

```text
1. AKTA returns review_required
2. System emits review_trigger with decision/record binding
3. Reviewer receives artifact packet (ai_output, record, evidence state, blocked_tools, next_admissible_steps)
4. Reviewer approves scoped next step only
5. Runtime re-evaluates or applies scoped authorization
6. New AKTA Record documents the approved transition
```

## Anti-patterns

- **Review laundering (F6)** — disclaimers do not bypass review for mutating tools
- **Stale review reuse (F14)** — prior approvals do not automatically authorize escalated actions
- **Global permission** — approval for one run plan does not authorize queue submission

## PF-Core bridge

PF-Core can enforce that mutating tools require a valid review trigger reference matching the current AKTA Record. See [pf_core_bridge.md](pf_core_bridge.md).

## CLI and API

Review triggers are embedded in decision JSON when `review_required`:

```bash
akta gate ... --out decision.json
# decision.json contains review_trigger when applicable
```

REST API `/v0/evaluate` returns full decision payload including review trigger fields.
