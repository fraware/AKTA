# AKTA Governance

## Project type

AKTA is an open protocol with a reference implementation under the MIT license. It is stewarded as a standalone engineering artifact for scientific action admissibility. It is not a safety certification.

## Decision-making

- **Protocol changes** (schemas, ontologies, deployment profiles): require design review and version bump.
- **Reference kernel changes**: follow normal pull request review.
- **Domain overlays**: core reference overlays (generic lab, materials, computational science) are operational. Biology, chemistry, and clinical overlays are experimental and not deployment-ready without institutional governance.

## Versioning

AKTA follows semantic versioning for the reference implementation package (`akta-protocol`, currently v1.0.0). Schema versions are embedded in artifact metadata (e.g., `akta-core-v1.0`, `akta-record-v0.5`).

See also `policy/scope_compatibility_manifest.json` for SCOPE contract pins and [docs/policy_integrity.md](docs/policy_integrity.md) for effective policy provenance.

## Compatibility and release keys

- SCOPE/AKTA contract negotiation uses pinned versions in `policy/scope_compatibility_manifest.json` (strict mode: exact match).
- Policy HMAC / Ed25519 release-key rotation: revoke compromised key IDs in the signing registry, regenerate `effective_policy_manifest.json`, and fail closed under `AKTA_PRODUCTION_MODE` / `AKTA_REQUIRE_SIGNED_POLICY`. See [docs/policy_integrity.md](docs/policy_integrity.md).
- RFCs for protocol changes belong in design review before schema freezes; prefer small, versioned schema bumps over silent semantic drift.

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
