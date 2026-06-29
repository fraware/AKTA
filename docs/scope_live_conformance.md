# Live SCOPE conformance (v0.8.1)

AKTA verifies live SCOPE integration through `scripts/verify_scope_live_chain.py`, contract tests under `tests/contracts/`, and pilot-mode bundle verification.

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
export AKTA_STRICT_SCOPE_CONTRACT=1             # hard-fail fixture/runtime version mismatch
```

## Assurance truthfulness (v0.8.1)

| Adapter mode | Summary IAL/SAL source | Notes |
|--------------|------------------------|-------|
| `simulated` | Fixed `IAL0` / `SAL0` | Contract simulation only; never institutional assurance |
| `cli`, `python-import` | SCOPE grant/decision provenance when present; else `IAL0` / `SAL0` | AKTA-synthesized summary; `summary_origin` records provenance backing |
| `akta-review-cli` | SCOPE `summary.json` | Authoritative live contract |

Synthetic summaries must not claim institutional or high assurance without SCOPE provenance. Pilot verification enforces this.

## Pilot mode verifier

```bash
make demo-pilot-bundle          # dist/pilot_bundle/ (live SCOPE when env set)
make verify-pilot-bundle        # --pilot-mode checks
python scripts/verify_reconstructable_cross_repo.py --pilot-mode dist/pilot_bundle
```

Pilot mode requires:

- Real SCOPE summary (`scope akta review` paths) or provenance-backed synthesis
- `identity_assurance_level` and `signing_assurance_level` present
- Rejects `adapter_mode=simulated` and `summary_origin` in (`akta_simulated`, `akta_synthesized`)

## Failure conditions

The verifier fails closed when:

- Adapter falls back to `simulated` mode (pilot mode and cross-repo gate)
- Review packet is synthetic (no `packet_id`, or `adapter_mode: simulated`)
- SCOPE decision lacks `decision_id`
- Grant lacks `authorization.approved_scope` (real v0.5+ shape)
- PCS export accepts an overbroad grant (must reject)
- akta-review `summary.json` fails schema validation
- AKTA fixture `contract_version` mismatches expected pin when `AKTA_STRICT_SCOPE_CONTRACT=1`

## Acceptance demos

```bash
SCOPE_REPO_PATH=../SCOPE python scripts/demo_akta_scope_protocol_drift.py
SCOPE_CLI=scope python scripts/demo_akta_scope_protocol_drift.py
SCOPE_CLI=scope SCOPE_CLI_MODE=akta-review python scripts/verify_scope_live_chain.py --mode akta-review
SCOPE_REPO_PATH=../SCOPE make demo-pilot-bundle
make verify-pilot-bundle
```

Output must include `adapter_mode=python-import`, `cli`, or `akta-review-cli` — never `simulated` for pilot bundles.

## Fixtures

Version-pinned contract fixtures: `tests/fixtures/scope_scope_order.json`, `scope_valid_narrowing.json` with `contract_version: akta-scope-contract-v0.8.1`.

Real artifact shapes for contract tests: `tests/contracts/fixtures/real_scope_v06/` and `tests/fixtures/scope_grants/`.

When the sibling SCOPE repo is absent, integration tests skip with a clear message; default CI uses mocks and fixtures.

Public release checklist: [RELEASE.md](RELEASE.md).
