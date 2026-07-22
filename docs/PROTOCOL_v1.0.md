# AKTA Protocol v1.0

Protocol freeze declaration for the Open Scientific Action Protocol reference implementation.

## Frozen schemas (v1.0)

- `akta_decision.schema.json`
- `akta_record.schema.json`
- `akta_review_trigger.schema.json`
- PCS manifest contract (via PCS-Core integration)
- SCOPE review summary contract (`scope-akta-review-v0.9+`)

## Policy bundle

- Manifest: `akta-policy-manifest-v1.0`
- Bundle: `akta-core-v1.0`
- Reference integrity: Ed25519-signed release bundle (see [policy_integrity.md](policy_integrity.md))

## Non-certification

AKTA v1.0 is a reference kernel and field benchmark — not safety certification, not institutional IRB approval, and not a guarantee of scientific correctness.

## External review checklist (non-blocking)

- [ ] Independent lab reproduces `make ci` on tagged release
- [ ] SCOPE live gate passes with sibling checkout
- [ ] Pilot bundle quality report `all_ok=true` on release tag
- [ ] Oracle-independent eval 100% on public hand-written slice
- [ ] Holdout eval passes (labels private)

## Version claims at v1.0

| Claim | Requirement |
|-------|-------------|
| Reference kernel | Always (`make ci`) |
| Field benchmark v1 | M3 corpus + `make eval-bench-v1` |
| Live trust stack | M2 sibling matrix + release-gate CI |
| Protocol v1.0 | This document + policy freeze |
