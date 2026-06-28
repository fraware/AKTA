# Domain Overlays

Domain overlays modify AKTA-Core rules for specific scientific domains.

## Operational overlays (v0.4)

| Overlay | Domain |
|---------|--------|
| `generic_lab_v0.yaml` | Generic lab default |
| `materials_v0.yaml` | Materials science labs |
| `computational_science_v0.yaml` | Computational science workflows |
| `biology_v0.yaml` | Biology / biosafety |
| `chemistry_v0.yaml` | Chemistry / chemical safety |
| `clinical_v0.yaml` | Clinical / IRB-governed research |

Each operational overlay includes:

- `minimum_evidence_for` (A5–A10 action families)
- `hazard_triggers` with decision escalation
- `requested_scope_overrides` for SCOPE mapping
- `required_review_roles` per action family
- `tool_restrictions` for domain-specific tools

Legacy aliases `biology_placeholder`, `chemistry_placeholder`, and `clinical_placeholder` resolve to the v0.4 operational files for scenario compatibility.
