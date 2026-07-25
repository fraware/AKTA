# ADR 0001 — Admissibility boundary

## Status

Accepted (AKTA-AS-00)

## Context

AKTA sits between model output and scientific action. Integrators sometimes treat gate decisions as truth certification, SCOPE replacement, or a learning loop over pilot outcomes. The AS hardening workstream needs an explicit boundary before adding reconstructable artifacts and pilot modes.

## Decision

AKTA is an **admissibility boundary**: it admits, refuses, or routes a proposed scientific action under pinned policy, evidence context, and deployment profile.

AKTA does **not**:

1. Certify scientific truth, correctness, or institutional efficacy
2. Replace SCOPE reviewer identity verification, grant lifecycle, or signing
3. Replace PF-Core runtime enforcement or PCS-Core release packaging as sibling systems of record
4. Run general reinforcement learning or update policy from pilot outcome metrics
5. Authorize P7 fully autonomous scientific operator behavior (taxonomy-only; runtime refused)

Pilot metrics (AS-07) are privacy-preserving operational aggregates for disagreement, blocking rates, and reconstruction completeness — not efficacy scores that feed back into policy learning.

## Consequences

- Docs and ADRs must restate these non-claims at release boundaries (AS-08).
- New schemas/CLIs are additive; frozen PROTOCOL v1.0 required fields remain unchanged.
- Fail-closed institutional pins (including placeholder release signers) stay fail-closed.
