# Cross-repo CI configuration (v0.6)

AKTA default CI runs entirely in-repo. Optional jobs validate live exports against sibling repositories when repository variables or secrets are configured.

## Repository variables

Set these under **Settings → Secrets and variables → Actions → Variables**:

| Variable | Purpose | Activates job |
|----------|---------|---------------|
| `PF_CORE_REPO_PATH` | Absolute path to a checked-out PF-Core repo on the runner | `cross-repo-pf-pcs` (PF step) |
| `PCS_CORE_REPO_PATH` | Absolute path to a checked-out PCS-Core repo | `cross-repo-pf-pcs` (PCS step) |
| `SCOPE_REPO_PATH` | Absolute path to a checked-out SCOPE repo | `cross-repo-scope` |
| `PCS_BENCH_REPO_PATH` | Absolute path to a checked-out PCS-Bench repo | `cross-repo-pcs-bench` |

## Repository secrets

| Secret | Purpose |
|--------|---------|
| `SCOPE_REPO_URL` | Git clone URL for SCOPE; CI clones to `$GITHUB_WORKSPACE/scope-sibling` and sets `SCOPE_REPO_PATH` |

## Manual sibling checkout pattern

Self-hosted or composite runners with sibling repos on disk:

```yaml
env:
  PF_CORE_REPO_PATH: /opt/siblings/PF-Core
  PCS_CORE_REPO_PATH: /opt/siblings/PCS-Core
  SCOPE_REPO_PATH: /opt/siblings/SCOPE
  PCS_BENCH_REPO_PATH: /opt/siblings/PCS-Bench
```

Run locally:

```powershell
$env:PF_CORE_REPO_PATH = "C:\path\to\PF-Core"
$env:PCS_CORE_REPO_PATH = "C:\path\to\PCS-Core"
$env:SCOPE_REPO_PATH = "C:\path\to\SCOPE"
$env:PCS_BENCH_REPO_PATH = "C:\path\to\PCS-Bench"
pytest tests/contracts/ -v -m integration
```

## Job behavior

### `cross-repo-pf-pcs`

Runs when `PF_CORE_REPO_PATH` or `PCS_CORE_REPO_PATH` is non-empty. Exports AKTA artifacts and validates against sibling PF-Core / PCS-Core validators via `tests/contracts/cross_repo_helpers.py`.

### `cross-repo-scope`

Runs when `SCOPE_REPO_PATH` is set or `SCOPE_REPO_URL` secret is present. Clones SCOPE when only the secret is configured, then runs SCOPE python-import contract tests.

### `cross-repo-pcs-bench`

Runs when `PCS_BENCH_REPO_PATH` is set. Invokes external PCS-Bench runner when available; contract tests verify in-repo fallback when the path is unset.

## External PCS-Bench integration

When `PCS_BENCH_REPO_PATH` points to a sibling checkout, `adapters/pcs_bench/runner.run_pcs_bench_suite()` attempts, in order:

1. Python import: `pcs_bench.runners.akta.run_akta_suite`
2. CLI script: `scripts/run_akta_suite.py`
3. In-repo `AKTABenchScenario` runner (default)

## Fail-closed defaults

- Jobs are skipped when variables are unset; default CI remains green without siblings.
- Invalid `PCS_BENCH_REPO_PATH` values fall back to the in-repo runner rather than silently passing external validation.
- SCOPE python-import mode does not fall back to simulated grants when `SCOPE_REPO_PATH` is set.

See also [tests/contracts/README.md](../tests/contracts/README.md).
