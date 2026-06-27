# SCOPE Bridge — AKTA Review Trigger Consumption

AKTA emits SCOPE-compatible review triggers when admissibility is `review_required` or `authorization_required`. SCOPE (Scientific Control and Oversight Protocol) orchestrates human review workflows; AKTA supplies the typed trigger artifact that binds a specific scientific action transition to a scoped review obligation.

## Division of responsibility

| System | Role |
|--------|------|
| AKTA | Pre-action admissibility decision and review trigger emission |
| SCOPE | Review routing, artifact packet assembly, approval lifecycle |
| PF-Core | Post-action proof that runtime honored the AKTA decision |
| PCS-Core | Packaging of AKTA Records and review artifacts for memory/bench |

## Trigger artifact

Review triggers conform to `schemas/review_trigger.schema.json`. Required fields for SCOPE consumption:

| Field | SCOPE use |
|-------|-----------|
| `review_trigger_id` | Unique trigger handle for approval records |
| `decision_id` | Bind to AKTA Decision that produced the trigger |
| `source_record_id` | Bind to AKTA Record (may be provisional pre-record export) |
| `required_review_role` | Route to protocol_owner, domain_scientist, compute_lead, etc. |
| `review_scope` | Typed scope: `experimental_plan_review`, `queue_prioritization_review`, etc. |
| `review_artifacts_required` | Minimum evidence packet contents |
| `blocked_tools` / `allowed_next_steps` | Scoped permission surface |
| `approval_effect` | Must remain scoped; not global permission |
| `default_expiration` | Typically `single_run` |
| `policy_hash` / `tool_registry_hash` | Integrity binding to trusted policy |
| `consequentiality` / `consequentiality_reason` | v0.2 escalation context |
| `review_trigger_hash` | Content integrity for trigger artifact |

## Consumption workflow

```text
1. Runtime calls AKTA Gate before mutating tool invocation
2. AKTA returns review_required with embedded review_trigger
3. SCOPE receives trigger via:
   - decision JSON (`review_trigger` field)
   - `akta review-trigger export --decision ... --out review_trigger.json`
   - PCS bundle (`review_trigger.json` when present)
4. SCOPE assembles review_artifacts_required packet
5. Reviewer approves scoped next step only (matches allowed_next_steps)
6. Runtime re-evaluates or applies scoped authorization token
7. New AKTA Record documents the approved transition
```

## CLI export

```bash
akta gate --output ai_output.json --tool experiment_planner.create_run_plan \
  --profile P5_review_gated_experimental_planner --context context.json --out decision.json

akta review-trigger export --decision decision.json --out review_trigger.json
```

## PCS bundle inclusion

When a record includes `review_trigger`, PCS export adds `review_trigger.json` to the bundle and lists it in `manifest.json` files. SCOPE can ingest the bundle directly without re-deriving trigger fields from the decision.

## Anti-patterns (SCOPE must enforce)

- **Review laundering (F6)** — disclaimers in `scientific_context` do not bypass review for mutating tools
- **Stale review reuse (F14)** — prior `prior_review_id` metadata does not authorize escalated actions
- **Global permission** — approval for one run plan must not authorize queue submission or active protocol mutation
- **Hash mismatch** — triggers with `policy_hash` not matching trusted policy must be rejected

## Schema validation

SCOPE should validate incoming triggers against `review_trigger.schema.json` before routing. AKTA validates triggers at emission when `validate_output=True` on the gate.

## Related documentation

- [review_integration.md](review_integration.md) — AKTA review trigger semantics
- [pcs_export.md](pcs_export.md) — PCS bundle layout including review triggers
- [pf_core_bridge.md](pf_core_bridge.md) — Runtime enforcement after review
