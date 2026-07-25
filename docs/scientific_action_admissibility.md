# Scientific Action Admissibility

> **Current status:** Package **1.2.0**. Boundary and non-claims: [adr/0001-admissibility-boundary.md](adr/0001-admissibility-boundary.md), [limitations.md](limitations.md). Operators: [operator_pilot_guide.md](operator_pilot_guide.md). Protocol freeze: [PROTOCOL_v1.0.md](PROTOCOL_v1.0.md).

Scientific action admissibility is the decision layer that determines whether an AI-generated scientific output is allowed to become, shape, trigger, or prepare a scientific action.

## The category

AKTA sits between AI-generated scientific reasoning and AI-shaped scientific action. It does not decide scientific truth. It decides whether an output may influence what science does next under explicit evidence, validation, review, tool, deployment, and domain constraints.

## Core workflow

```text
AI output
→ requested action/tool
→ scientific action classification
→ evidence and validation assessment
→ deployment-profile policy
→ admissibility decision
→ tool gate
→ AKTA Record
```

## Admissibility decisions

| Decision | Meaning |
|----------|---------|
| allowed | Action permitted under policy |
| allowed_with_logging | Permitted; AKTA Record required |
| draft_only | Draft output only; no active mutation |
| review_required | Typed review must precede action |
| authorization_required | Explicit authorization required |
| blocked | Inadmissible under current constraints |
| abstain_insufficient_context | Cannot classify safely; mutating actions blocked |

## Composition rule

An action must satisfy deployment-profile policy and evidence-to-action policy. The strictest decision wins.

## Core norm

If AI changes what science does next, there should be an AKTA Record.

AKTA is an open protocol with a reference implementation. It is not a safety certification.
