# Reviewer pilot guide

Guidance for human reviewers consuming AKTA review triggers and shadow comparisons during pilots.

## What to review

1. **Decision reason + decision basis** — policy clauses, missing evidence, contradictions, next admissible steps
2. **Bindings** — digests for evidence/VSA bundle, policy/overlay/tool registry, IDs
3. **Uniform failure** (when present) — `uniform_class` plus preserved `local_reason_code`
4. **Pilot mode flags** — `shadow` / `operational_influence` must be false for shadow paths that must not authorize execution

## Shadow disagreement

When AKTA runs in `prospective_shadow`, record a comparison artifact (human vs AKTA). Disagreement feeds pilot metrics; it does not auto-change policy.

## SCOPE handoff

Review triggers bind `decision_id` / `record_id` and policy hashes. Do not approve grants that omit these bindings in institutional pilots.

## Non-claims

- Reviewer approval via SCOPE is still required for authorization-gated actions
- AKTA does not replace IRB/biosafety/EHS review
- Reconstruction verifies artifact integrity, not experimental replication in nature
- Uniform failure classes and local reason codes explain refusal/routing; they do not certify scientific truth

## Acceptance questions

- Can another operator reconstruct this decision from the release bundle (`akta reconstruct`)?
- Are outcome links append-only without rewriting admissibility?
- Did shadow outputs stay non-operational (`operational_influence: false`)?

See [operator_pilot_guide.md](operator_pilot_guide.md), [failure_class_taxonomy.md](failure_class_taxonomy.md), and [adr/0003-artifact-immutability-and-reconstruction.md](adr/0003-artifact-immutability-and-reconstruction.md).
