# Domain Overlays

Domain overlays modify AKTA-Core rules for specific scientific domains.

## Governance tiers (v0.5)

| Tier | Deployment in production |
|------|--------------------------|
| `core_reference` | Allowed |
| `experimental_domain_overlay` | Refused (high-risk domains) |
| `expert_reviewed_domain_overlay` | Allowed when institutionally approved |
| `institutional_deployment_overlay` | Allowed |

When `AKTA_PRODUCTION_MODE=1`, biology, chemistry, and clinical overlays (experimental tier) are refused unless upgraded to expert-reviewed or institutional tier.

Each overlay includes:

- `tier`, `maintainer`, `review_status`, `review_date`, `non_certification_statement`
- `minimum_evidence_for` (A5–A10 action families)
- `hazard_triggers` with decision escalation
- `requested_scope_overrides` for SCOPE mapping
- `required_review_roles` per action family
- `tool_restrictions` for domain-specific tools

## Operational overlays (v0.5)

| Overlay | Domain | Tier |
|---------|--------|------|
| `generic_lab_v0.yaml` | Generic lab default | core_reference |
| `materials_v0.yaml` | Materials science labs | core_reference |
| `computational_science_v0.yaml` | Computational science workflows | core_reference |
| `biology_v0.yaml` | Biology / biosafety | experimental_domain_overlay |
| `chemistry_v0.yaml` | Chemistry / chemical safety | experimental_domain_overlay |
| `clinical_v0.yaml` | Clinical / IRB-governed research | experimental_domain_overlay |

| `materials_expert_v0.yaml` | Materials science (expert-reviewed) | expert_reviewed_domain_overlay |

Legacy aliases `biology_placeholder`, `chemistry_placeholder`, and `clinical_placeholder` resolve to the experimental overlay files for scenario compatibility.

## Expert-reviewed overlay governance (v0.6)

To promote an overlay to `expert_reviewed_domain_overlay`:

1. Domain working group reviews hazard triggers, minimum evidence, and tool restrictions
2. Add `expert_signoff` block with reviewer IDs, roles, agreement notes, and signoff date
3. Set `tier: expert_reviewed_domain_overlay` and `review_status: expert_reviewed`
4. Include `non_certification_statement` (expert review is not safety certification)
5. Open PR with overlay diff; maintainers verify production mode accepts the tier

Reference example: `materials_expert_v0.yaml`.
