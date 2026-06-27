# Domain Overlay Guide

Domain overlays extend AKTA core policy with field-specific constraints without modifying the core policy bundle.

## Purpose

Overlays encode domain science norms that the generic kernel cannot assume:

- Minimum evidence thresholds for recommendations, planning, and queue prioritization
- Required review roles for sensitive action types
- Blocked action types for immature domains
- Tool-specific restrictions

## Overlay files

Overlays live in `overlays/` as YAML files validated against `schemas/domain_overlay.schema.json`.

| Overlay | Status | Domain |
|---------|--------|--------|
| `generic_lab_v0.yaml` | Operational | Generic laboratory |
| `materials_v0.yaml` | Operational | Materials science |
| `computational_science_v0.yaml` | Operational | Computational science |
| `biology_placeholder.yaml` | Placeholder | Biology |
| `chemistry_placeholder.yaml` | Placeholder | Chemistry |
| `clinical_placeholder.yaml` | Placeholder | Clinical (non-operational) |

## Key fields

```yaml
domain: materials
version: materials_v0.1
operational: true

minimum_evidence_for:
  recommendation: E4_internally_consistent_evidence
  experimental_planning: E4_internally_consistent_evidence
  queue_prioritization: E5_internally_replicated_evidence

required_review_roles:
  protocol_modification:
    - protocol_owner
  queue_prioritization:
    - domain_scientist

blocked_actions: []

tool_restrictions:
  workflow.update_state:
    decision: review_required
```

## Composition rule

Overlay decisions participate in the strictest-decision composition alongside deployment profile and evidence matrices. An overlay block or evidence threshold violation can tighten a permissive profile decision.

## Integrity

Every decision and record includes `domain_overlay_hash` when an overlay is applied. Tampering with overlay files changes the hash, enabling detection of overlay manipulation.

## Usage

```python
decision = gate.evaluate(
    ...,
    domain_overlay="materials_v0",
)
```

```bash
akta gate ... --domain-overlay materials_v0
```

## Authoring guidelines

1. Keep overlays declarative — no executable logic
2. Prefer minimum evidence thresholds over blanket blocks where possible
3. Mark immature domains as `operational: false`
4. Document metadata requirements for audit reconstruction
5. Version overlays independently from core policy
