# AKTA Field Thesis

## The problem

AI-for-science systems are crossing from reasoning to action. Models summarize literature, interpret evidence, draft protocols, recommend experiments, call tools, and prepare execution-adjacent workflows. Each of these outputs can change what science does next — even when the model frames the output as informal, preliminary, or "just a suggestion."

The field lacks a shared decision layer for when those outputs are admissible to shape scientific action.

## The category: scientific action admissibility

AKTA defines **scientific action admissibility** as the decision of whether an AI-generated scientific output may become, shape, trigger, or prepare a scientific action under explicit evidence, validation, review, tool, deployment, and domain constraints.

This is distinct from:

- **Scientific truth** (what is correct) — addressed by verification systems like VSA
- **Runtime enforcement** (what actually ran) — addressed by PF-Core
- **Artifact packaging** (what is preserved) — addressed by PCS-Core

AKTA sits at the pre-action boundary: before consequential tools execute.

## Core norm

If AI changes what science does next, there should be an AKTA Record.

## Design principles

1. **Pre-action, not post-hoc** — evaluate before tool execution
2. **Action, not intention** — classify implied scientific action, not disclaimers
3. **Evidence limits action** — weak evidence cannot automatically drive prioritization, protocol changes, or execution
4. **Review must be typed** — role, scope, artifacts, expiration
5. **Tool calls are scientific actions** — mutating tools require gating
6. **Blocking must be constructive** — every block returns next admissible steps
7. **Strictest decision wins** — compose profile, evidence, overlay, registry, and handoff layers

## Deployment profiles

Profiles P0–P6 represent increasing autonomy. P7 (fully autonomous scientific operator) is defined for taxonomy only and is not supported in v0.1.

## Helpful Boundedness

The primary evaluation metric balances safety and usefulness. Systems should remain scientifically useful while respecting evidence, validation, review, and tool boundaries. AKTA penalizes both unsafe overreach and useless overblocking.

## Position in the trust stack

```text
VSA (evidence grounding) → AKTA (action admissibility) → PF-Core (runtime proof) → PCS (artifact packaging)
```

AKTA does not replace adjacent systems. It provides the missing admissibility decision that connects evidence assessment to runtime enforcement and long-term scientific memory.
