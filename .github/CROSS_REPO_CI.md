# Cross-repo CI configuration (v1.0)

AKTA default CI (`make ci`) runs entirely in-repo. The **release-gate** workflow runs on every PR to `main` and additionally exercises the live trust-stack when sibling clone URLs or repository variables are configured.

## Repository variables (self-hosted / pre-checked-out siblings)

Set under **Settings → Secrets and variables → Actions → Variables**:

| Variable | Purpose |
|----------|---------|
| `PF_CORE_REPO_PATH` | Absolute path to PF-Core checkout on the runner |
| `PCS_CORE_REPO_PATH` | Absolute path to PCS-Core checkout |
| `SCOPE_REPO_PATH` | Absolute path to SCOPE checkout (optional if clone secret set) |
| `PCS_BENCH_REPO_PATH` | Absolute path to PCS-Bench checkout |
| `VSA_REPO_PATH` | Absolute path to VSA checkout |
| `MEMORY_REPO_PATH` | Absolute path to Scientific Memory checkout |

When a `*_REPO_PATH` variable is set but the path is missing, release-gate **fails closed** (does not silently skip).

## Repository secrets (clone URLs)

Set under **Settings → Secrets and variables → Actions → Secrets**:

| Secret | Purpose |
|--------|---------|
| `SCOPE_REPO_URL` | Git clone URL for SCOPE |
| `PF_CORE_REPO_URL` | Git clone URL for PF-Core |
| `PCS_CORE_REPO_URL` | Git clone URL for PCS-Core |
| `PCS_BENCH_REPO_URL` | Git clone URL for PCS-Bench |
| `VSA_REPO_URL` | Git clone URL for VSA |
| `MEMORY_REPO_URL` | Git clone URL for Scientific Memory |

Optional **public** fallbacks (repository variables) when secrets are unset:

| Variable | Default public URL |
|----------|-------------------|
| `SCOPE_PUBLIC_REPO_URL` | `https://github.com/fraware/SCOPE.git` |
| `PF_CORE_PUBLIC_REPO_URL` | `https://github.com/SentinelOps-CI/provability-fabric-core.git` |
| `PCS_CORE_PUBLIC_REPO_URL` | `https://github.com/SentinelOps-CI/pcs-core.git` |
| `PCS_BENCH_PUBLIC_REPO_URL` | `https://github.com/fraware/pcs-bench.git` |
| `VSA_PUBLIC_REPO_URL` | `https://github.com/fraware/verified-science-agent.git` |
| `MEMORY_PUBLIC_REPO_URL` | `https://github.com/fraware/scientific-memory.git` |

The composite action `.github/actions/clone-siblings` clones configured siblings and exports `SCOPE_REPO_PATH`, `PF_CORE_REPO_PATH`, etc. to `GITHUB_ENV`.

**SCOPE is mandatory on release-gate:** if clone fails, the workflow fails. Default public SCOPE URL is used when no secret is configured.

## Manual sibling checkout pattern

```bash
export PF_CORE_REPO_PATH=/path/to/PF-Core
export PCS_CORE_REPO_PATH=/path/to/PCS-Core
export SCOPE_REPO_PATH=/path/to/SCOPE
export PCS_BENCH_REPO_PATH=/path/to/PCS-Bench
export VSA_REPO_PATH=/path/to/verified-science-agent
export MEMORY_REPO_PATH=/path/to/scientific-memory
pytest tests/contracts/ -v -m integration
python scripts/verify_v1_release.py
```

## Release-gate jobs

| Job | Runs on PR | Purpose |
|-----|------------|---------|
| `scope-live-gate` | Yes | Live SCOPE (python-import mandatory), pilot bundle, strict contract |
| `sibling-live-matrix` | Yes | PF runtime proof, PCS ingest, PCS-Bench harness, VSA, Memory |
| `eval-bench-v1` | Yes | Oracle-independent, holdout, adversarial, behavioral, gate-derived metrics |

## External PCS-Bench integration

When `PCS_BENCH_REPO_PATH` is set, `adapters.pcs_bench.external_harness.run_external_harness()` shells to the sibling PCS-Bench CLI or falls back to `adapters.pcs_bench.runner.run_pcs_bench_suite()`.

## Fail-closed defaults

- SCOPE live gate never skips all verification steps on PRs (public clone URL fallback).
- Sibling steps fail when repository `*_REPO_PATH` variables are set but paths are missing.
- Invalid sibling paths for PCS-Bench fall back to in-repo runner only when the variable is unset.

## Branch protection (required checks)

Configure on `main`:

- `CI` (`.github/workflows/ci.yml`) — `make ci`
- `Release Gate / scope-live-gate`
- `Release Gate / eval-bench-v1`

Optional but recommended when sibling secrets are configured:

- `Release Gate / sibling-live-matrix`

See [docs/RELEASE.md](../docs/RELEASE.md).
