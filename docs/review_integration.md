# Review Integration

AKTA emits typed review triggers when admissibility is `review_required` or `authorization_required`.

## Review trigger schema (v0.3)

Review triggers conform to `schemas/review_trigger.schema.json` with `review_trigger_version = "0.3"`:

| Field | Purpose |
|-------|---------|
| `review_trigger_id` | Unique trigger identifier |
| `akta_decision_id` / `decision_id` | Bound AKTA Decision (aliases) |
| `akta_record_id` / `source_record_id` | Bound AKTA Record (aliases) |
| `requested_scope` | **Required** SCOPE machine-enforced approval scope |
| `review_route` | Optional human/process routing hint |
| `required_review_role` | Who must review |
| `review_artifacts_required` | Evidence packet contents |
| `approval_effect` | Scoped permission, not global |
| `default_expiration` | Typically `single_run` |

Tool-to-scope mapping is defined in `policy/tool_to_requested_scope.yaml`. See [scope_bridge.md](scope_bridge.md).

## Default review roles

| Action type | Default role |
|-------------|--------------|
| A5 protocol modification | protocol_owner |
| A6 experimental planning | domain_scientist |
| A7 queue prioritization | domain_scientist |
| A8 workflow mutation | workflow_owner |
| A9 execution-adjacent | lab_safety_officer |
| A10 publication claim | domain_scientist |

Domain overlays may override roles (e.g., `compute_lead` for computational science).

## Integration workflow

```text
1. AKTA returns review_required or authorization_required
2. System emits review_trigger with requested_scope and decision/record binding
3. SCOPE routes review; reviewer receives artifact packet
4. Reviewer approves scoped next step only (grant must match requested_scope)
5. Runtime re-evaluates or applies scoped authorization via PF-Core
6. New AKTA Record documents the approved transition
```

## Authority-transfer boundary

AKTA assigns `requested_scope`; SCOPE grants approval scope. A narrow grant must not authorize out-of-scope tools. Demonstrated in `examples/integrated_protocol_drift/`.

## CLI export

```bash
akta review-trigger export --decision decision.json --out review_trigger.json
```

## SCOPE simulator (no local SCOPE repo)

Use `akta.scope_contract` helpers or `tests/contracts/` for field extraction and grant validation when SCOPE is not checked out locally.
