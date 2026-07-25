# ADR 0003 — Artifact immutability and reconstruction

## Status

Accepted (AKTA-AS-00; implemented across AS-01/03/07/08)

## Context

Institutional pilots require that an admissibility decision can be reconstructed from frozen evidence and pinned policy. Outcome linkage must not rewrite the original verdict.

## Decision

1. **Pinned material inputs.** Decisions/records bind digests for question, evidence report, claim set, proposed action, VSA decision-time bundle, policy/overlay/tool-registry hashes, tool, action class, and IDs (AS-01 binding set).
2. **Decision basis.** Structured `decision_basis` cites loaded policy clauses and evidence gaps; constructive `next_admissible_steps` must not be silently emptied on blocks (AS-03).
3. **Immutable historical artifacts.** Original `admissibility` and binding digests are immutable after emission. Outcome links are append-only (`outcome_ref` events / `integrations.outcome_refs[]`) with `verdict_mutation: false` (AS-07). Attempts to rewrite admissibility fail closed (`policy_block` / schema failure).
4. **Reconstruction.** `akta reconstruct --release …` rebuilds a reconstruction report from a release bundle using the same library as demo/verify scripts (AS-08). Frozen evidence + pinned policy must be sufficient to explain the decision.

## Consequences

- New artifact types get dedicated schema files; existing decision/record schemas gain optional additive fields only.
- Exporters (SCOPE trigger, PF, PCS) bind `decision_id`/`record_id` and digests; tamper/mismatch fails closed when mode requires it.
- Pilot metrics must not include raw private evidence text.
