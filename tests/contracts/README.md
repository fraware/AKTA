# Cross-repo contract tests

Contract tests validate AKTA exports against pinned fixtures and JSON schemas. They run in CI without sibling repositories.

## In-repo (default CI)

```bash
pytest tests/contracts/ tests/integration/ -v
```

| Module | Validates |
|--------|-----------|
| `test_scope_trigger_contract.py` | SCOPE review trigger shape, `requested_scope`, ID aliases |
| `test_pf_obligation_contract.py` | PF-Core obligation schema and enforcement fields |
| `test_pcs_manifest_contract.py` | PCS manifest schema, review trigger inclusion |
| `test_pcs_full_chain_tamper.py` | PCS v0.5 full-chain tamper detection (all artifacts) |
| `test_cross_repo_live.py` | Optional PF-Core / PCS-Core live validation |
| `test_pcs_bench_external.py` | PCS-Bench external checkout + in-repo fallback |
| `test_pcs_contract.py` (integration) | Round-trip PCS export from live gate |

Fixtures live in `tests/contracts/fixtures/`. Regenerate pinned hashes after intentional schema bumps:

```bash
python scripts/update_expected_v03.py   # scope + PCS fixtures helper
python scripts/regenerate_policy_manifest.py
```

## Live sibling repos (optional)

Set repository paths and run contract tests against live exports:

```powershell
$env:PF_CORE_REPO_PATH = "C:\path\to\PF-Core"
$env:PCS_CORE_REPO_PATH = "C:\path\to\PCS-Core"
$env:SCOPE_REPO_PATH = "C:\path\to\SCOPE"
$env:PCS_BENCH_REPO_PATH = "C:\path\to\PCS-Bench"
$env:SCOPE_CLI = "scope"   # SCOPE CLI on PATH, or full path

pytest tests/contracts/ tests/integration/ -v -m integration
```

### GitHub Actions (v0.6)

Optional CI jobs activate when repository variables are set:

| Variable / Secret | Job |
|-------------------|-----|
| `PF_CORE_REPO_PATH` | `cross-repo-pf-pcs` — PF obligation live validation |
| `PCS_CORE_REPO_PATH` | `cross-repo-pf-pcs` — PCS bundle live validation |
| `SCOPE_REPO_PATH` or `SCOPE_REPO_URL` secret | `cross-repo-scope` — SCOPE python-import contract tests |
| `PCS_BENCH_REPO_PATH` | `cross-repo-pcs-bench` — external PCS-Bench integration contract |

Full variable and secret documentation: [.github/CROSS_REPO_CI.md](../../.github/CROSS_REPO_CI.md).

Default CI does not require sibling repos.

### SCOPE CLI mode (v0.5+)

When `SCOPE_CLI` is set (without `SCOPE_REPO_PATH`), `adapters/scope/client.py` invokes:

```text
scope packet create --trigger <trigger.json> [--record <record.json>] --out <packet.json>
scope decision submit --packet <packet.json> --grant-scope <scope> --reviewer <id> --out <decision.json>
scope grant issue --decision <decision.json> --out <grant.json>
```

### SCOPE python-import mode

When `SCOPE_REPO_PATH` is set, the adapter imports `ScopeEngine` (or compat aliases) from the sibling repo. Expected methods are documented in `adapters/scope/engine_protocol.py`.

See [docs/scope_bridge.md](../../docs/scope_bridge.md) for trigger fields and anti-patterns.

### PF-Core / PCS-Core

AKTA exports obligations and artifact bundles via:

```bash
akta export pf --record akta_record.json --decision akta_decision.json --out dist/pf/ --validate
akta export pcs --record akta_record.json --decision akta_decision.json --out dist/pcs/ --validate
```

Compare exported JSON against sibling repo validators when available. In-repo tests use `schemas/pf_core_obligation.schema.json` and `schemas/pcs_akta_artifact.schema.json`.

Live validation helpers: `tests/contracts/cross_repo_helpers.py`.
