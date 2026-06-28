# AKTA Governance

## Project type

AKTA is an open protocol with a reference implementation. It is stewarded as a standalone engineering artifact for scientific action admissibility.

## Decision-making

- **Protocol changes** (schemas, ontologies, deployment profiles): require design review and version bump.
- **Reference kernel changes**: follow normal pull request review.
- **Domain overlays**: core reference overlays (generic lab, materials, computational science) are operational. Biology, chemistry, and clinical overlays are experimental (v0.5) and not deployment-ready without institutional governance.

## Versioning

AKTA follows semantic versioning for the reference implementation package (`akta-protocol`). Schema versions are embedded in artifact metadata (e.g., `akta-core-v0.5`, `akta-record-v0.5`).

## Non-certification

AKTA does not certify autonomous labs, safety compliance, or scientific correctness. The AKTA Card is an institutional disclosure artifact, not a certification.

## P7 exclusion

Deployment profile P7 (fully autonomous scientific operator) is defined for future taxonomy only. AKTA raises `UnsupportedProfileError` if P7 is requested. **P7 runtime is a permanent non-goal** unless the Open Scientific Action Protocol specification explicitly adds P7 support in a future version.

## Maintainers

Initial stewardship: [fraware/AKTA](https://github.com/fraware/AKTA) repository maintainers.
