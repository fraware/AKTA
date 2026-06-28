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
| `test_pcs_contract.py` (integration) | Round-trip PCS export from live gate |

Fixtures live in `tests/contracts/fixtures/`. Regenerate pinned hashes after intentional schema bumps:

```bash
python scripts/update_expected_v03.py   # scope + PCS fixtures helper
```

## Live sibling repos (optional)

Set repository paths and run the same contract tests against live exports:

```powershell
$env:PF_CORE_REPO_PATH = "C:\path\to\PF-Core"
$env:PCS_CORE_REPO_PATH = "C:\path\to\PCS-Core"
$env:SCOPE_REPO_PATH = "C:\path\to\SCOPE"
$env:SCOPE_CLI = "scope"   # SCOPE CLI on PATH, or full path

pytest tests/contracts/ tests/integration/ -v
```

### SCOPE subprocess mode

When `SCOPE_CLI` or `SCOPE_REPO_PATH` is set, `adapters/scope/client.py` invokes:

```text
scope review --stdin [--repo <SCOPE_REPO_PATH>]
```

stdin JSON: `{"trigger": {...}, "grant_scope": "...", "reviewer_id": "..."}`

stdout JSON: `{"review_packet": {...}, "grant": {...}, "decision": {...}}`

See [docs/scope_bridge.md](../../docs/scope_bridge.md) for trigger fields and anti-patterns.

### PF-Core / PCS-Core

AKTA exports obligations and artifact bundles via:

```bash
akta export pf --record akta_record.json --decision akta_decision.json --out dist/pf/ --validate
akta export pcs --record akta_record.json --decision akta_decision.json --out dist/pcs/ --validate
```

Compare exported JSON against sibling repo validators when available. In-repo tests use `schemas/pf_core_obligation.schema.json` and `schemas/pcs_akta_artifact.schema.json`.
