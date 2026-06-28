# Domain Overlay Guide

Domain overlays extend AKTA core policy with field-specific constraints without modifying the core policy bundle.

## Purpose

Overlays encode domain science norms that the generic kernel cannot assume:

- Minimum evidence thresholds for recommendations, planning, and queue prioritization
- Required review roles for sensitive action types
- Hazard triggers with decision escalation
- SCOPE `requested_scope` overrides
- Tool-specific restrictions

## Governance tiers (v0.5+)

| Tier | Production deployment |
|------|----------------------|
| `core_reference` | Allowed |
| `experimental_domain_overlay` | Refused when `AKTA_PRODUCTION_MODE=1` |
| `expert_reviewed_domain_overlay` | Allowed when institutionally approved |
| `institutional_deployment_overlay` | Allowed |

See [overlays/README.md](../overlays/README.md) for tier promotion workflow.

## Overlay files

Overlays live in `overlays/` as YAML files validated against `schemas/domain_overlay.schema.json`.

| Overlay | Tier | Domain |
|---------|------|--------|
| `generic_lab_v0.yaml` | core_reference | Generic laboratory |
| `materials_v0.yaml` | core_reference | Materials science |
| `computational_science_v0.yaml` | core_reference | Computational science |
| `materials_expert_v0.yaml` | expert_reviewed_domain_overlay | Materials science (expert-reviewed) |
| `biology_v0.yaml` | experimental_domain_overlay | Biology / biosafety |
| `chemistry_v0.yaml` | experimental_domain_overlay | Chemistry / chemical safety |
| `clinical_v0.yaml` | experimental_domain_overlay | Clinical / IRB-governed research |

Legacy aliases `biology_placeholder`, `chemistry_placeholder`, and `clinical_placeholder` resolve to the experimental overlay files for scenario compatibility.

Experimental overlays are not deployment-ready without institutional governance. Expert review is not safety certification.

## Key fields

```yaml
domain: materials
version: materials_v0.1
tier: core_reference
operational: true
non_certification_statement: "This overlay is not a safety certification."

minimum_evidence_for:
  recommendation: E4_internally_consistent_evidence
  experimental_planning: E4_internally_consistent_evidence
  queue_prioritization: E5_internally_replicated_evidence

required_review_roles:
  protocol_modification:
    - protocol_owner
  queue_prioritization:
    - domain_scientist

hazard_triggers: []

requested_scope_overrides: {}

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
3. Mark immature domains as `experimental_domain_overlay` with `operational: false` where appropriate
4. Include `non_certification_statement` on every overlay
5. Version overlays independently from core policy
