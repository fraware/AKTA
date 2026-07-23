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
## Supply-chain / release evidence (WS14)

| Control | Placement |
|---------|-----------|
| Full wheel smoke | `python -m akta.wheel_smoke` after clean wheel install (schemas, grant auth, status, containment, evidence, PF/PCS) |
| Reproducibility | Second build under `SOURCE_DATE_EPOCH`; **fails** unless digests match or `docs/reproducibility_normalization.md` lists an allowed token |
| Sibling matrix on tags | `.github/workflows/release-gate.yml` requires full PF/PCS/SCOPE/VSA/Memory matrix on `v*` |
| Release evidence report | `scripts/build_release_evidence_report.py` → `dist/release_evidence.json` |
| VSA pin | `903d834f…` (`v0.7.2`); missing checkout / SHA mismatch remain fail-closed |

## Sibling pins (P1-A)

Institutional release pins live in `policy/release_pins.yaml` and are recorded in
`scripts/verify_v1_release.py --institutional` reports. Missing checkouts or SHA
mismatches stay fail-closed — never silently optionalized under institutional_release.
