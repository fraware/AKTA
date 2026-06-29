# Inter-rater protocol (AKTA-Bench v1)

AKTA-Bench v1 labels for public scenarios follow a lightweight two-reviewer protocol. Holdout labels remain private and are not published.

## Reviewers

- Reviewer A: domain scientist (primary)
- Reviewer B: governance engineer (secondary)

## Process

1. Each reviewer independently assigns expected admissibility without running the gate on the scenario during review.
2. Disagreements are resolved in a consensus session; unresolved cases are excluded from oracle-independent metrics.
3. Metadata recorded per row in `scenarios/expected_decisions.jsonl`:
   - `reviewer_ids`
   - `inter_rater_agreement` (0.0–1.0)
   - `label_source` (`oracle_independent`, `gate_derived`, `inter_rater_consensus`)

## Coverage target

At least 80% of public expected-decision rows include inter-rater metadata for v1.0 field credibility.

## Gate-derived split

Scenarios labeled `gate_derived` are reported separately in eval output via `scenarios/public_gate_derived.jsonl` and must not be mixed with oracle-independent pass rates.
