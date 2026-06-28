# SCOPE Bridge — AKTA Review Trigger Consumption

AKTA emits SCOPE-compatible review triggers when admissibility is `review_required` or `authorization_required`. SCOPE (Scientific Control and Oversight Protocol) orchestrates human review workflows; AKTA supplies the typed trigger artifact that binds a specific scientific action transition to a scoped review obligation.

## Division of responsibility

| System | Role |
|--------|------|
| AKTA | Pre-action admissibility decision and review trigger emission |
| SCOPE | Review routing, artifact packet assembly, scoped grant lifecycle |
| PF-Core | Post-action proof that runtime honored the AKTA decision |
| PCS-Core | Packaging of AKTA Records and review artifacts for memory/bench |

**Authority boundary:** AKTA assigns `requested_scope`; SCOPE grants approval scope. AKTA does not broaden SCOPE grants. SCOPE grants do not override AKTA evidence or deployment-profile policy by default. After authorization, AKTA re-gates via `evaluate_with_grant()` using `prior_review_allowed_tools` and `prior_review_blocked_tools`.

## Trigger artifact (v0.3)

Review triggers conform to `schemas/review_trigger.schema.json` with `review_trigger_version = "0.3"`.

| Field | SCOPE use |
|-------|-----------|
| `review_trigger_id` | Unique trigger handle for approval records |
| `akta_decision_id` / `decision_id` | Bind to AKTA Decision (aliases for compatibility) |
| `akta_record_id` / `source_record_id` | Bind to AKTA Record |
| `requested_scope` | **Required** machine-enforced SCOPE approval scope enum |
| `review_route` | Optional human/process routing hint |
| `required_review_role` | Route to protocol_owner, domain_scientist, compute_lead, etc. |
| `review_artifacts_required` | Minimum evidence packet contents |
| `blocked_tools` / `allowed_next_steps` | Scoped permission surface |
| `approval_effect` | Must remain scoped; not global permission |
| `default_expiration` | Typically `single_run` |
| `policy_hash` / `tool_registry_hash` | Integrity binding to trusted policy |
| `consequentiality` / `consequentiality_reason` | Escalation context |
| `review_trigger_hash` | Content integrity for trigger artifact |

### SCOPE approval scopes (`requested_scope` enum)

- `protocol_draft`
- `active_protocol_update`
- `single_validation_plan`
- `single_validation_run_draft`
- `single_run_queue_priority`
- `robot_queue_submission`
- `execution_payload_preparation`
- `publication_claim`
- `scientific_memory_import`

Tool-to-scope mapping lives in `policy/tool_to_requested_scope.yaml`. AKTA never emits values outside this enum.

## Consumption workflow

```text
1. Runtime calls AKTA Gate before mutating tool invocation
2. AKTA returns review_required with embedded review_trigger (requested_scope set)
3. SCOPE receives trigger via:
   - decision JSON (`review_trigger` field)
   - `akta review-trigger export --decision ... --out review_trigger.json`
   - PCS bundle (`review_trigger.json` when present)
4. SCOPE assembles review_artifacts_required packet
5. Reviewer approves scoped next step only (matches allowed_next_steps / granted scope)
6. Runtime re-evaluates via evaluate_with_grant() or applies scoped authorization token
7. New AKTA Record documents the approved transition
```

## Authority-transfer boundary

AKTA assigns `requested_scope`; SCOPE grants approval scope. A narrow grant (e.g. `protocol_draft` when `active_protocol_update` was requested) must not authorize active mutation or robot execution. See `examples/integrated_protocol_drift/` and `scripts/demo_akta_scope_protocol_drift.py`.

## Contract testing without SCOPE repo

When SCOPE is not checked out locally, use `tests/contracts/scope_fixtures.py` to simulate field extraction and approval scope validation.

## CLI export

```bash
akta gate --output ai_output.json --tool protocol_editor.update_active_protocol \
  --profile P4_protocol_drafting_assistant --context context.json --out decision.json

akta review-trigger export --decision decision.json --out review_trigger.json
```

## SCOPE adapter (v0.7.1)

`adapters/scope/client.py` supports four modes (auto-detected):

| Mode | When | Behavior |
|------|------|----------|
| **simulated** | Default (no env vars) | Contract simulation via `akta/scope_contract.py` |
| **python-import** | `SCOPE_REPO_PATH` set | Imports `scope.ScopeEngine` from sibling repo |
| **cli** | `SCOPE_CLI` set, no akta-review mode | Three-step: packet create, decision submit, grant issue |
| **akta-review-cli** | `SCOPE_CLI` + `SCOPE_CLI_MODE=akta-review` | `scope akta review`; validates `summary.json` |

Priority: `SCOPE_REPO_PATH` → python-import; else `SCOPE_CLI` with mode → cli or akta-review-cli; else simulated.

No simulated fallback when `SCOPE_REPO_PATH` or `SCOPE_CLI` is configured.

### CLI setup (v0.5.1 three-step command shapes)

Temp files written per invocation: `review_trigger.json`, `akta_record.json` (when record present), `reviewer.json`, `decision_input.json`.

```bash
export SCOPE_CLI=scope
python scripts/demo_akta_scope_protocol_drift.py
```

Commands invoked:

```text
scope packet create --akta-trigger <review_trigger.json> [--akta-record <akta_record.json>] --out <scope_review_packet.json>
scope decision submit --packet <scope_review_packet.json> --reviewer <reviewer.json> --decision <decision_input.json> --out <scope_decision.json>
scope grant issue --packet <scope_review_packet.json> --decision <scope_decision.json> --out <scope_grant.json>
```

`decision_input.json` uses `type: approve_narrower_scope` when narrowing `active_protocol_update` to `protocol_draft`.

### akta-review CLI setup (v0.7.1)

```bash
export SCOPE_CLI=scope
export SCOPE_CLI_MODE=akta-review
python scripts/verify_scope_live_chain.py --mode akta-review
```

Output `summary.json` must conform to `schemas/scope_akta_review_summary.schema.json`.

### Python import setup

```bash
export SCOPE_REPO_PATH=/path/to/SCOPE
python scripts/demo_akta_scope_protocol_drift.py
```

Invalid grants fail before PCS export. See [tests/contracts/README.md](../tests/contracts/README.md), [scope_live_conformance.md](scope_live_conformance.md), and `adapters/scope/engine_protocol.py`.

## PCS bundle inclusion

When a record includes `review_trigger`, PCS export adds `review_trigger.json` to the bundle and lists it in `manifest.json` files. Full-chain exports may also include `scope_review_packet.json`, `scope_decision.json`, and `scope_grant.json`.

## Anti-patterns (SCOPE must enforce)

- **Review laundering (F6)** — disclaimers in `scientific_context` do not bypass review for mutating tools
- **Stale review reuse (F14)** — prior `prior_review_id` metadata does not authorize escalated actions
- **Global permission** — approval for one run plan must not authorize queue submission or active protocol mutation
- **Hash mismatch** — triggers with `policy_hash` not matching trusted policy must be rejected
- **Scope mismatch** — grants must not exceed `requested_scope` without AKTA re-evaluation
- **Grant override (v0.7.1)** — SCOPE grants must not be treated as blanket overrides of AKTA evidence or profile policy

## Related documentation

- [akta_v03_integration.md](akta_v03_integration.md) — v0.3 integration summary
- [review_integration.md](review_integration.md) — AKTA review trigger semantics
- [scope_live_conformance.md](scope_live_conformance.md) — Live SCOPE verification
- [pcs_export.md](pcs_export.md) — PCS bundle layout including review triggers
- [pf_core_bridge.md](pf_core_bridge.md) — Runtime enforcement after review
