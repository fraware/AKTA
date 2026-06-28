# Live SCOPE conformance (v0.7.1)

AKTA verifies live SCOPE integration through `scripts/verify_scope_live_chain.py` and contract tests under `tests/contracts/`.

## Modes

| Mode | Command | Requirement |
|------|---------|-------------|
| python-import | `python scripts/verify_scope_live_chain.py --scope-repo ../SCOPE --mode python-import` | Sibling SCOPE repo with v0.5+ `ScopeEngine.from_policy_dir` |
| cli | `python scripts/verify_scope_live_chain.py --scope-cli scope --mode cli` | SCOPE CLI on PATH (three-step packet/decision/grant) |
| akta-review-cli | `python scripts/verify_scope_live_chain.py --scope-cli scope --mode akta-review` | SCOPE CLI with `SCOPE_CLI_MODE=akta-review` (`scope akta review`) |

Environment equivalents:

```bash
export SCOPE_REPO_PATH=/path/to/SCOPE          # python-import
export SCOPE_CLI=scope                          # cli or akta-review-cli
export SCOPE_CLI_MODE=akta-review               # akta-review-cli only
```

## Failure conditions

The verifier fails closed when:

- Adapter falls back to `simulated` mode
- Review packet is synthetic (no `packet_id`, or `adapter_mode: simulated`)
- SCOPE decision lacks `decision_id`
- Grant lacks `authorization.approved_scope` (real v0.5+ shape)
- PCS export accepts an overbroad grant (must reject)
- akta-review `summary.json` fails schema validation

## Acceptance demos

```bash
SCOPE_REPO_PATH=../SCOPE python scripts/demo_akta_scope_protocol_drift.py
SCOPE_CLI=scope python scripts/demo_akta_scope_protocol_drift.py
SCOPE_CLI=scope SCOPE_CLI_MODE=akta-review python scripts/verify_scope_live_chain.py --mode akta-review
```

Output must include `adapter_mode=python-import`, `cli`, or `akta-review-cli` — never `simulated`.

## Fixtures

Real artifact shapes for contract tests: `tests/contracts/fixtures/real_scope_v06/` and `tests/fixtures/scope_grants/`.

When the sibling SCOPE repo is absent, integration tests skip with a clear message; default CI uses mocks and fixtures.

Public release checklist: [RELEASE.md](RELEASE.md).
