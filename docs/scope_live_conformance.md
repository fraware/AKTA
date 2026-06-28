# Live SCOPE conformance (v0.7)

AKTA verifies live SCOPE integration through `scripts/verify_scope_live_chain.py` and contract tests under `tests/contracts/`.

## Modes

| Mode | Command | Requirement |
|------|---------|-------------|
| python-import | `python scripts/verify_scope_live_chain.py --scope-repo ../SCOPE --mode python-import` | Sibling SCOPE repo with v0.5+ `ScopeEngine.from_policy_dir` |
| cli | `python scripts/verify_scope_live_chain.py --scope-cli scope --mode cli` | SCOPE CLI on PATH |

Environment equivalents: `SCOPE_REPO_PATH` or `SCOPE_CLI`.

## Failure conditions

The verifier fails closed when:

- Adapter falls back to `simulated` mode
- Review packet is synthetic (no `packet_id`, or `adapter_mode: simulated`)
- SCOPE decision lacks `decision_id`
- Grant lacks `authorization.approved_scope` (real v0.6 shape)
- PCS export accepts an overbroad grant (must reject)

## Acceptance demos

```bash
SCOPE_REPO_PATH=../SCOPE python scripts/demo_akta_scope_protocol_drift.py
SCOPE_CLI=scope python scripts/demo_akta_scope_protocol_drift.py
```

Output must include `adapter_mode=python-import` or `adapter_mode=cli`, never `simulated`.

## Fixtures

Real artifact shapes for contract tests: `tests/contracts/fixtures/real_scope_v06/`.

When the sibling SCOPE repo is absent, integration tests skip with a clear message; default CI uses mocks and fixtures.
