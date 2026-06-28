# AKTA Governance

## Project type

AKTA is an open protocol with a reference implementation under the MIT license. It is stewarded as a standalone engineering artifact for scientific action admissibility. It is not a safety certification.

## Decision-making

- **Protocol changes** (schemas, ontologies, deployment profiles): require design review and version bump.
- **Reference kernel changes**: follow normal pull request review.
- **Domain overlays**: core reference overlays (generic lab, materials, computational science) are operational. Biology, chemistry, and clinical overlays are experimental and not deployment-ready without institutional governance.

## Versioning

AKTA follows semantic versioning for the reference implementation package (`akta-protocol`, currently v0.7.1). Schema versions are embedded in artifact metadata (e.g., `akta-core-v0.5`, `akta-record-v0.5`).

## Non-certification

AKTA does not certify autonomous labs, safety compliance, or scientific correctness. The AKTA Card is an institutional disclosure artifact, not a certification. PCS export records provenance; it does not certify deployment safety.

## Authority boundary

AKTA decides pre-action admissibility. SCOPE grants scoped authorization after human review. AKTA does not broaden SCOPE grants; SCOPE grants do not override AKTA evidence or deployment-profile policy by default.

## P7 exclusion

Deployment profile P7 (fully autonomous scientific operator) is defined for future taxonomy only. AKTA raises `UnsupportedProfileError` if P7 is requested. **P7 runtime is a permanent non-goal** unless the Open Scientific Action Protocol specification explicitly adds P7 support in a future version.

## Release acceptance

Public releases follow [docs/RELEASE.md](docs/RELEASE.md): `make ci`, integrated demos, and optional live SCOPE verification.

## Maintainers

Initial stewardship: [fraware/AKTA](https://github.com/fraware/AKTA) repository maintainers.
