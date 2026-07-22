# CI supply-chain notes

## Pinned actions

Workflows under `.github/workflows/` pin third-party GitHub Actions to full commit SHAs (with version tags in comments). Prefer Dependabot/Renovate updates that refresh both SHA and comment together.

## Recommended follow-ons (stubs)

These are not required for the v1.0 reference-kernel green bar, but fit the existing CI structure:

| Control | Suggested placement |
|---------|---------------------|
| `pip-audit` | Optional job after `pip install -e ".[dev,security]"`; fail on known high/critical CVEs in direct deps |
| CodeQL | Separate workflow on `push`/`pull_request` for Python; keep queries default |
| SBOM | Emit CycloneDX/SPDX on tag builds and attach next to pilot bundle artifacts |

Do not block merge on sibling-repo CodeQL/SBOM until those jobs are wired and green.
