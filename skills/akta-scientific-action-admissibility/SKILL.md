---
name: akta-scientific-action-admissibility
description: >-
  Evaluates scientific action admissibility using the AKTA protocol (v0.7.1).
  Classifies AI outputs (A0-A10), assigns responsibility levels, applies evidence
  and deployment profile policy, gates tool calls, emits AKTA Records, and produces
  SCOPE-compatible review triggers with requested_scope. Use when integrating
  AI-for-science agents, gating lab tools, evaluating weak evidence escalation,
  protocol drift, literature-to-action laundering, multi-agent handoffs, SCOPE review
  routing, grant re-gating, or when the user mentions AKTA, scientific action admissibility,
  or authority transfer.
---

# AKTA Scientific Action Admissibility (v0.7.1)

## Quick start

```bash
pip install -e ".[dev]"

akta gate \
  --output ai_output.json \
  --tool lab_scheduler.prioritize \
  --profile P2_analysis_assistant \
  --context context.json \
  --out akta_decision.json

akta record --decision akta_decision.json --out akta_record.json
akta review-trigger export --decision akta_decision.json --out review_trigger.json

# SCOPE adapter: simulated | python-import (SCOPE_REPO_PATH) | cli (SCOPE_CLI) | akta-review-cli (SCOPE_CLI_MODE=akta-review)
python scripts/demo_akta_scope_protocol_drift.py
python scripts/demo_reconstructable_experiment.py
python evals/run_oracle_independent.py
python -m adapters.mcp.server
```

## When to apply AKTA

Run AKTA **before** any tool that mutates scientific state:

- Lab schedulers, protocol editors, experiment planners
- Robot queues, workflow mutators, publication tools
- Multi-agent pipelines where responsibility may escalate

Do **not** use AKTA to decide scientific truth — use VSA for evidence grounding.

## Workflow

1. **Import evidence context** — optionally map VSA report via `adapters/vsa/import_report.py`
2. **Evaluate admissibility** — `AKTAGate.evaluate()` or `akta gate`
3. **Gate tool call** — block if `admissibility` is `blocked`, `abstain_insufficient_context`, `review_required`, or `authorization_required`
4. **Emit record** — `decision.to_record()` for every non-trivial decision
5. **Export integrations** — PF-Core obligation (`akta export pf`), PCS bundle (`akta export pcs`)
6. **SCOPE handoff** — when review is required, export `review_trigger` with `requested_scope`; after grant, call `evaluate_with_grant()`

## Grant re-gate (v0.7.1)

After SCOPE authorization:

```python
decision = gate.evaluate_with_grant(
    ai_output=...,
    requested_tool=...,
    scope_grant=grant,
    context=...,
    deployment_profile=...,
)
```

Grant tool lists map to `prior_review_allowed_tools` and `prior_review_blocked_tools`. SCOPE grants do not auto-override weak-evidence or profile blocks.

## Review context

Prior review metadata in `context.metadata` is enforced:

- `prior_review_expired` — expired grants require new review (F14)
- `prior_review_scope` — narrow grants block out-of-scope tools
- `prior_review_allowed_tools` / `prior_review_blocked_tools` — grant-exact tool lists (v0.7.1)
- `prior_akta_records` — blocked prior records prevent escalation

Structured classification via `context.structured_action` takes priority over NL regex. Optional LLM classifier requires `AKTA_LLM_CLASSIFIER=1` and `OPENAI_API_KEY`.

## Review trigger (v0.3 schema)

When review or authorization is required, AKTA emits a trigger with:

- `requested_scope` — required SCOPE approval scope enum (see `policy/tool_to_requested_scope.yaml`)
- `review_route` — optional human/process routing hint
- `akta_decision_id` / `akta_record_id` — ID aliases for downstream binding
- `review_trigger_version` — `"0.3"`

Use `examples/integrated_protocol_drift/` for AKTA x SCOPE integration; `examples/reconstructable_experiment/` for post-grant re-gate Cases A/B/C.

## Decision composition

Strictest decision wins across layers:

- Deployment profile admissibility matrix
- Evidence-to-action matrix
- Domain overlay constraints (minimum evidence, hazard triggers, scope overrides)
- Tool registry permissions
- Multi-agent handoff escalation
- Grant constraints after SCOPE authorization

## Admissibility outcomes

| Decision | Action |
|----------|--------|
| `allowed` | Proceed |
| `allowed_with_logging` | Proceed; emit record |
| `draft_only` | Draft output only; no active mutation |
| `review_required` | Typed review before action; emit `requested_scope` |
| `authorization_required` | Explicit authorization required; emit `requested_scope` |
| `blocked` | Do not execute; return `next_admissible_steps` |
| `abstain_insufficient_context` | Unknown mutating tool; fail closed |

## Python API

```python
from akta import AKTAGate, AKTAContext

gate = AKTAGate.from_policy_dir("policy/")
decision = gate.evaluate(
    ai_output={"summary": "..."},
    requested_tool="lab_scheduler.prioritize",
    requested_action="prioritize_next_run",
    context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
    deployment_profile="P2_analysis_assistant",
    domain_overlay="generic_lab_v0",
)

if decision.admissibility in ("blocked", "abstain_insufficient_context"):
    pass  # surface decision.next_admissible_steps
elif decision.admissibility in ("review_required", "authorization_required"):
    trigger = decision.to_dict()["review_trigger"]
    scope = trigger["requested_scope"]
else:
    record = decision.to_record()
```

## Security requirements

- Verify `policy_hash`, `tool_registry_hash`, and `domain_overlay_hash` in every decision
- Unknown mutating tools must abstain (`abstain_insufficient_context`)
- P7 fully autonomous profile is not supported
- Narrow SCOPE grants must not authorize out-of-scope tool calls
- AKTA is not a safety certification

## Examples

See [examples/weak_evidence_gate.md](examples/weak_evidence_gate.md) and [examples/multi_agent_handoff.md](examples/multi_agent_handoff.md).

## Additional resources

- Protocol overview: [docs/scientific_action_admissibility.md](../../docs/scientific_action_admissibility.md)
- Integration guide: [docs/integration_guide.md](../../docs/integration_guide.md)
- SCOPE bridge: [docs/scope_bridge.md](../../docs/scope_bridge.md)
- Live SCOPE conformance: [docs/scope_live_conformance.md](../../docs/scope_live_conformance.md)
- Threat model: [docs/threat_model.md](../../docs/threat_model.md)
- Failure taxonomy F01–F15: [docs/failure_class_taxonomy.md](../../docs/failure_class_taxonomy.md)
