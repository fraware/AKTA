---
name: akta-scientific-action-admissibility
description: >-
  Evaluates scientific action admissibility using the AKTA protocol. Classifies
  AI outputs (A0-A10), assigns responsibility levels, applies evidence and
  deployment profile policy, gates tool calls, and emits AKTA Records. Use when
  integrating AI-for-science agents, gating lab tools, evaluating weak evidence
  escalation, protocol drift, literature-to-action laundering, multi-agent handoffs,
  or when the user mentions AKTA, scientific action admissibility, or authority transfer.
---

# AKTA Scientific Action Admissibility

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

## Decision composition

Strictest decision wins across layers:

- Deployment profile admissibility matrix
- Evidence-to-action matrix
- Domain overlay constraints
- Tool registry permissions
- Multi-agent handoff escalation

## Admissibility outcomes

| Decision | Action |
|----------|--------|
| `allowed` | Proceed |
| `allowed_with_logging` | Proceed; emit record |
| `draft_only` | Draft output only; no active mutation |
| `review_required` | Typed review before action |
| `authorization_required` | Explicit authorization required |
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
    # Do not call tool; surface decision.next_admissible_steps
    pass
else:
    record = decision.to_record()
```

## Security requirements

- Verify `policy_hash`, `tool_registry_hash`, and `domain_overlay_hash` in every decision
- Unknown mutating tools must abstain (`abstain_insufficient_context`)
- P7 fully autonomous profile is not supported in v0.1

## Examples

See [examples/weak_evidence_gate.md](examples/weak_evidence_gate.md) and [examples/multi_agent_handoff.md](examples/multi_agent_handoff.md).

## Additional resources

- Protocol overview: [docs/scientific_action_admissibility.md](../../docs/scientific_action_admissibility.md)
- Integration: [docs/integration_guide.md](../../docs/integration_guide.md)
- Failure taxonomy F1-F15: [evals/graders.py](../../evals/graders.py)
