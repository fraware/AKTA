# Review Integration

AKTA emits typed review triggers when admissibility is `review_required` or `authorization_required`. After SCOPE authorization, closed-loop re-gating applies grant constraints without overriding evidence or deployment-profile policy.

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

## Closed-loop re-gate (v0.7)

After SCOPE issues a grant, AKTA applies grant metadata then re-evaluates the requested action:

```python
decision = gate.evaluate_with_grant(
    ai_output=...,
    requested_tool=...,
    scope_grant=grant,
    context=...,
    deployment_profile=...,
)
```

Grant fields mapped to context metadata:

| Grant field | Context metadata | Enforcement |
|-------------|------------------|-------------|
| `allowed_tools` | `prior_review_allowed_tools` | Tool must be on allowlist when present |
| `blocked_tools` | `prior_review_blocked_tools` | Blocked tools take precedence |
| `authorization.approved_scope` | `prior_review_scope` | Out-of-scope tools blocked (F14) |
| Grant expiry | `prior_review_expired` | Expired grants require new review (F14) |

**Grant vs policy:** Weak evidence under `P2_analysis_assistant` may still block queue prioritization after a narrow SCOPE grant. SCOPE authorization does not automatically override AKTA evidence or profile matrices.

See `akta/review_loop.py`, `examples/reconstructable_experiment/reconstruction_report.md`, and [limitations.md](limitations.md).

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
5. Runtime calls evaluate_with_grant() with scope_grant metadata
6. AKTA re-gates: grant tool lists + evidence/profile/overlay layers
7. PF-Core enforces resulting obligation; new AKTA Record documents the transition
```

## Authority-transfer boundary

AKTA assigns `requested_scope`; SCOPE grants approval scope. A narrow grant must not authorize out-of-scope tools. Demonstrated in `examples/integrated_protocol_drift/` and reconstructable experiment Case C.

## CLI export

```bash
akta review-trigger export --decision decision.json --out review_trigger.json
```

## SCOPE simulator (no local SCOPE repo)

Use `akta.scope_contract` helpers or `tests/contracts/` for field extraction and grant validation when SCOPE is not checked out locally.

Live verification with sibling repo: [scope_live_conformance.md](scope_live_conformance.md).
