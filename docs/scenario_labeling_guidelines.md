# Scenario labeling guidelines

## Primary failure class

Each benchmark scenario must declare exactly one primary `failure_mode` / `failure_class` from the F01–F15 taxonomy when the scenario tests a specific failure mode.

## Label sources

`expected_decisions.jsonl` rows may include:

| Field | Purpose |
|-------|---------|
| `label_source` | `oracle_independent`, `inter_rater_consensus`, or `gate_derived` |
| `reviewer_ids` | Non-empty unique list when human reviewers contributed |
| `inter_rater_agreement` | Float in [0.0, 1.0] when consensus or agreement is recorded |

## Inter-rater consensus

Use `inter_rater_consensus` only when multiple reviewers agreed on the expected admissibility label. Include `inter_rater_agreement` reflecting reviewer agreement strength.

## Oracle-independent labels

Oracle-independent scenarios (`scenarios/oracle_independent.jsonl`) must use `label_source: oracle_independent`. Labels are hand-written and not derived from the gate oracle at label time.

## Adversarial transitions

Each row in `scenarios/adversarial_transitions.jsonl` must include `failure_class` matching the primary risk under test. Transition eval reports per-class pass/fail in `evals/reports/adversarial_transitions.json`.

## Holdout scenarios

Holdout rows (`holdout: true` in scenario JSONL) must not leak into public benchmark training or prompt tuning. See [holdout_private_governance.md](holdout_private_governance.md).
