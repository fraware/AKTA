# Multi-Agent Handoff Example

Responsibility escalates across a chain: literature → planner → scheduler.

## Handoff chain

| Agent | Action | Responsibility |
|-------|--------|----------------|
| literature_agent | A2 hypothesis | R1 |
| planner_agent | A6 experimental planning | R5 |
| scheduler_agent | A7 queue prioritization | R6 |

## Expected behavior

AKTA evaluates at the highest responsibility reached (R6) and applies handoff escalation rules. With E3 noisy evidence and P5 profile, prioritization is blocked.

## Commands

```bash
akta gate \
  --output examples/multi_agent_handoff/ai_output.json \
  --tool lab_scheduler.prioritize \
  --profile P5_review_gated_experimental_planner \
  --context examples/multi_agent_handoff/context.json \
  --domain-overlay generic_lab_v0 \
  --out /tmp/handoff_decision.json
```

## Key rule

Multi-agent handoff does not reduce responsibility. If the chain reaches resource allocation, the final tool call is gated at that level.
