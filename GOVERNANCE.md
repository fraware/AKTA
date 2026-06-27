# AKTA Governance

## Project type

AKTA is an open protocol with a reference implementation. It is stewarded as a standalone engineering artifact for scientific action admissibility.

## Decision-making

- **Protocol changes** (schemas, ontologies, deployment profiles): require design review and version bump.
- **Reference kernel changes**: follow normal pull request review.
- **Domain overlays**: operational overlays (materials, computational science, generic lab) are maintained in-repo; high-risk domain overlays (biology, chemistry, clinical) remain non-operational placeholders until domain expert review.

## Versioning

AKTA follows semantic versioning for the reference implementation package (`akta-protocol`). Schema versions are embedded in artifact metadata (e.g., `akta-core-v0.1`, `akta-record-v0.1`).

## Non-certification

AKTA does not certify autonomous labs, safety compliance, or scientific correctness. The AKTA Card is an institutional disclosure artifact, not a certification.

## P7 exclusion

Deployment profile P7 (fully autonomous scientific operator) is defined for future taxonomy only. AKTA v0.1 does not support or certify fully autonomous scientific operation.

## Maintainers

Initial stewardship: [fraware/AKTA](https://github.com/fraware/AKTA) repository maintainers.
