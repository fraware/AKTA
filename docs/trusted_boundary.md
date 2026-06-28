# Trusted Boundary

AKTA defines the trusted boundary between AI-generated scientific reasoning and AI-shaped scientific action.

## Boundary definition

The trusted boundary is the AKTA Gate evaluation point immediately before a tool call that may mutate scientific state or produce external effects.

```text
Untrusted side: AI model output, agent reasoning, multi-agent handoff chain
Trusted side:   Policy-bound admissibility decision, AKTA Record, PF obligation
```

## What crosses the boundary

| Crosses | Does not cross without review |
|---------|-------------------------------|
| Explanations (A0) | Protocol mutations (A5) |
| Literature search (A1) | Queue prioritization (A7) |
| Hypothesis generation (A2) | Execution-adjacent actions (A9) |
| Draft-only outputs | Active state mutations |

## Fail-closed rules

1. **Unknown mutating tools** → `abstain_insufficient_context`
2. **Unsupported profiles (P7)** → error, no evaluation
3. **Schema validation failure** → reject decision/record
4. **Policy hash mismatch** → integrity violation

## Trust anchors

Every decision and record carries:

- `policy_hash` — core policy bundle integrity
- `tool_registry_hash` — tool permission integrity
- `domain_overlay_hash` — overlay integrity (when applied)
- `record_hash` — record content integrity

## Deployment implications

Integrators should:

1. Load policy from a trusted, versioned source
2. Run AKTA Gate in the request path before tool dispatch
3. Refuse tool execution when admissibility is not `allowed` or `allowed_with_logging` (and appropriate for the action type)
4. Persist AKTA Records for audit reconstruction

## Relationship to PF-Core

AKTA decides at the boundary. PF-Core proves the runtime stayed within the boundary. SCOPE grants scoped authorization after human review; AKTA re-gates with `evaluate_with_grant()` without broadening grants or overriding evidence policy by default.

See [threat_model.md](threat_model.md) and [policy_integrity.md](policy_integrity.md).
