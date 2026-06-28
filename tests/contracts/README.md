# Cross-repo contract tests

Contract tests validate AKTA exports against pinned fixtures and JSON schemas. They run in CI without sibling repositories.

## In-repo (default CI)

```bash
pytest tests/contracts/ tests/integration/ -v
```

| Module | Validates |
|--------|-----------|
| `test_scope_trigger_contract.py` | SCOPE review trigger shape, `requested_scope`, ID aliases |
| `test_scope_akta_review_cli.py` | SCOPE akta-review CLI adapter and `summary.json` schema |
| `test_pf_obligation_contract.py` | PF-Core obligation schema and enforcement fields |
| `test_pcs_manifest_contract.py` | PCS manifest schema, review trigger inclusion |
| `test_pcs_full_chain_tamper.py` | PCS v0.5 full-chain tamper detection (all artifacts) |
| `test_pcs_scope_grant_export.py` | PCS grant validation (narrow/overbroad fixtures) |
| `test_cross_repo_live.py` | Optional PF-Core / PCS-Core live validation |
| `test_pcs_bench_external.py` | PCS-Bench external checkout + in-repo fallback |
| `test_pcs_contract.py` (integration) | Round-trip PCS export from live gate |

Fixtures live in `tests/contracts/fixtures/` and `tests/fixtures/scope_grants/`. Regenerate pinned hashes after intentional schema bumps:

```bash
python scripts/update_expected_v03.py
python scripts/regenerate_policy_manifest.py
```

## Live sibling repos (optional)

Set repository paths and run contract tests against live exports:

```bash
export PF_CORE_REPO_PATH=/path/to/PF-Core
export PCS_CORE_REPO_PATH=/path/to/PCS-Core
export SCOPE_REPO_PATH=/path/to/SCOPE
export PCS_BENCH_REPO_PATH=/path/to/PCS-Bench
export SCOPE_CLI=scope

pytest tests/contracts/ tests/integration/ -v -m integration
```

### GitHub Actions (v0.7.1)

Optional CI jobs activate when repository variables are set:

| Variable / Secret | Job |
|-------------------|-----|
| `PF_CORE_REPO_PATH` | `cross-repo-pf-pcs` — PF obligation live validation |
| `PCS_CORE_REPO_PATH` | `cross-repo-pf-pcs` — PCS bundle live validation |
| `SCOPE_REPO_PATH` or `SCOPE_REPO_URL` secret | `cross-repo-scope` — SCOPE python-import contract tests |
| `PCS_BENCH_REPO_PATH` | `cross-repo-pcs-bench` — external PCS-Bench integration contract |

Full variable and secret documentation: [.github/CROSS_REPO_CI.md](../../.github/CROSS_REPO_CI.md).

Default CI does not require sibling repos.

### SCOPE adapter modes (v0.7.1)

| Mode | Env | CLI shape |
|------|-----|-----------|
| python-import | `SCOPE_REPO_PATH` | `ScopeEngine.from_policy_dir`; v0.5 `create_packet`, `submit_decision`, `issue_grant` |
| cli | `SCOPE_CLI` | Three-step: packet create, decision submit, grant issue |
| akta-review-cli | `SCOPE_CLI` + `SCOPE_CLI_MODE=akta-review` | `scope akta review` → `summary.json` |
| simulated | (default) | In-repo contract simulation only |

Three-step CLI commands (v0.5.1):

```text
scope packet create --akta-trigger <trigger.json> [--akta-record <record.json>] --out <packet.json>
scope decision submit --packet <packet.json> --reviewer <reviewer.json> --decision <decision.json> --out <scope_decision.json>
scope grant issue --packet <packet.json> --decision <scope_decision.json> --out <scope_grant.json>
```

Live verification: `python scripts/verify_scope_live_chain.py`

See [docs/scope_bridge.md](../../docs/scope_bridge.md) and [docs/scope_live_conformance.md](../../docs/scope_live_conformance.md).

### PF-Core / PCS-Core

```bash
akta export pf --record akta_record.json --decision akta_decision.json --out dist/pf/ --validate
akta export pcs --record akta_record.json --decision akta_decision.json --out dist/pcs/ --validate
```

Compare exported JSON against sibling repo validators when available. In-repo tests use `schemas/pf_core_obligation.schema.json` and `schemas/pcs_akta_artifact.schema.json`.

Live validation helpers: `tests/contracts/cross_repo_helpers.py`.
