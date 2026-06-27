# Weak Evidence Gate Example

An AI agent interprets preliminary signal (E2) and attempts queue prioritization (A7/R6).

## Input

- `ai_output`: recommendation to prioritize condition B
- `requested_tool`: `lab_scheduler.prioritize`
- `deployment_profile`: `P2_analysis_assistant`
- `evidence_state`: `E2_preliminary_signal`

## Expected AKTA decision

```json
{
  "admissibility": "blocked",
  "scientific_action_type": "A7_resource_or_queue_prioritization",
  "responsibility_level": "R6_resource_allocation",
  "evidence_state": "E2_preliminary_signal"
}
```

## Commands

```bash
akta gate \
  --output examples/weak_evidence/ai_output.json \
  --tool lab_scheduler.prioritize \
  --profile P2_analysis_assistant \
  --context examples/weak_evidence/context.json \
  --out examples/weak_evidence/akta_decision.json
```

## Constructive blocking

AKTA returns `next_admissible_steps`:

- downgrade to hypothesis discussion
- draft a validation experiment
- request domain review before prioritization
