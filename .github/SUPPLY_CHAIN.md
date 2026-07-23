# CI supply-chain notes

## Pinned actions

Workflows under `.github/workflows/` pin third-party GitHub Actions to full commit SHAs (with version tags in comments). Prefer Dependabot/Renovate updates that refresh both SHA and comment together.

## Required CI controls (P1-B)

| Control | Placement |
|---------|-----------|
| Shared contract drift | `python scripts/assert_shared_contract_drift.py` |
| Ruff | Fail-closed on `akta/` + security paths; progressive on `adapters/` `tests/` |
| Mypy | Fail-closed on security-critical modules; progressive widen |
| pytest | Unit + integration + contracts + grant forgery |
| Schema conformance | `tests/test_schemas.py` |
| Policy manifest verification | Covered by policy integrity tests / institutional REST startup |
| Grant forgery lifecycle | `tests/test_grant_forgery_lifecycle.py` |
| Cross-contract | `tests/contracts/` |
| pip-audit | Fail-closed on declared deps |
| CodeQL | `.github/workflows/codeql.yml` (Python) |
| SBOM | CycloneDX JSON attached on package/tag builds when tooling available |
| Wheel build + twine check | `package` job |
| Wheel install smoke | Install built wheel into clean venv and import `akta` |
| Reproducibility comparison | Optional second wheel build hash compare when enabled |
| Package provenance hooks | GitHub Attestations / `actions/attest-build-provenance` on tags when available |

## Sibling pins (P1-A)

Institutional release pins live in `policy/release_pins.yaml` and are recorded in
`scripts/verify_v1_release.py --institutional` reports. Missing siblings stay
fail-closed placeholders — never silently optionalized under institutional_release.
