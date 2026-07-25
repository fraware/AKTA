# SCOPE sibling PR checklist

> **Current status:** Package **1.2.0** + AS hardening. This page is a **sibling coordination checklist** for SCOPE/shared-contracts pins in `policy/scope_compatibility_manifest.json` and `policy/release_pins.yaml` — those peer IDs are not the AKTA PyPI version. Prefer [RELEASE.md](RELEASE.md) and [integration_guide.md](integration_guide.md) for operator-facing release steps.

AKTA lands the authorization stack first. SCOPE (and other siblings) must
update integration constants in a coordinated PR so strict negotiation does not
fail closed on legacy IDs.

## Required constant updates in the SCOPE sibling

Align these with `policy/scope_compatibility_manifest.json`:

| Constant / field | Required value |
|------------------|----------------|
| `scope-protocol` package version | `2.1.0` or `2.1.1` |
| `scope-core` version | `scope-core-v2.1` (or `2.1.0` / `2.1.1`) |
| SCOPE policy / policy manifest version | `scope-policy-v2.1` |
| Authorization envelope schema | `scientific-authorization-envelope-v2` |
| Grant schema | `scope-grant-v2` |
| Grant status schema | `scope-grant-status-v1` |
| AKTA review contract | `scope-akta-review-v1.0` |
| Review summary contract | `scope-akta-review-summary-v1.0` |
| Fixture / AKTA SCOPE contract | `akta-scope-contract-v2.0` |
| Shared contracts package | `scientific-authorization-contracts==2.1.0` |
| Shared contracts release hash | match `policy/shared_contracts_pin.json` → `release_artifact_hash` |

## Legacy IDs that must be removed from strict negotiation

Do not advertise these under strict peer version declarations:

- `akta-capability-envelope-v1.0`
- `akta-scope-grant-v1.0`
- `akta-scope-contract-v1.0`
- `scope-core-v0.9` / `scope-core-v1.0`
- `scope-policy-v0.9` / `scope-policy-v1.0`

## Checkout pin verification

Existence of a sibling checkout is not enough. Release gates compare:

```text
git -C $SCOPE_REPO_PATH rev-parse HEAD
```

to the commit recorded in `policy/release_pins.yaml`. Mismatches fail closed under
`institutional_release` (`sibling_checkout_sha_mismatch`).

## Suggested sibling PR order

1. Land AKTA compatibility manifest + pins (this repo; package line **1.2.x**).
2. Open SCOPE PR updating peer version advertisements and installing shared contracts per the pin table above.
3. Re-run AKTA strict negotiation / cross-repo matrix against the pinned SCOPE SHA.
4. VSA checkout HEAD must align with `policy/release_pins.yaml` under institutional release (see [RELEASE.md](RELEASE.md) for the pinned tag).
