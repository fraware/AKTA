# AKTA Admissibility-Stack (AS) Baseline Freeze

Frozen baseline for the AKTA-AS-00–08 hardening workstream.

## Identity

| Field | Value |
|-------|-------|
| Package | `akta-protocol` |
| Version | `1.2.0` |
| Base commit | `4d23944657bb4a27f4056f03e4adbb9873d131a2` |
| Protocol freeze | [`PROTOCOL_v1.0.md`](PROTOCOL_v1.0.md) |
| Recorded at | 2026-07-24 |

## Toolchain

| Component | Version / command |
|-----------|-------------------|
| Python | `>=3.10` (baseline host: 3.13.11) |
| Install | `make install` → `pip install -e ".[dev,security]"` |
| Unit / contract tests | `make test` → `pytest tests/ skills/...` |
| Default CI | `make ci` |
| Bench regression | `make eval-bench-v1` |

## Reproducible commands (clean checkout)

```bash
git checkout 4d23944657bb4a27f4056f03e4adbb9873d131a2
python -m pip install -e ".[dev,security]"
make ci
make eval-bench-v1
```

Record stdout/exit codes in the PR body for AS-00. Default `make ci` is offline (no sibling repos required). Live SCOPE/PF/PCS conformance remains opt-in via sibling env vars.

## Protocol / benchmark claims (snapshot)

- Frozen protocol text: [`PROTOCOL_v1.0.md`](PROTOCOL_v1.0.md).
- Decision/record schemas already allow `additionalProperties: true` — AS work adds optional fields and **new** schema files; it does not rewrite frozen required fields.
- Bench failure classes remain F01–F15 in [`failure_class_taxonomy.md`](failure_class_taxonomy.md) / `evals/graders.py`.
- **Known debt (AS-04):** historical reports and some fixtures use `F1_` vs `F01_` naming drift. Mapping normalizes in the uniform-failure layer only; historical eval reports are not rewritten.

## Spine extended (not replaced)

| Component | Location |
|-----------|----------|
| CLI | `akta/cli.py` |
| Gate | `akta/gate.py` → classify → `akta/evaluate.py` → decision/record |
| VSA | `adapters/vsa/` |
| SCOPE | `adapters/scope/` + `akta/scope_*.py` |
| PF | `adapters/pf_core/` |
| PCS | `adapters/pcs/` |
| Scientific Memory | `adapters/scientific_memory/` |
| Release pins | `policy/release_pins.yaml` + `akta/release_pins.py` |
| Pilot stages (pre-AS-05) | `akta/pilot_workflow.py` |

## Non-claims (baseline)

AKTA admits or refuses a proposed scientific action under pinned policy. This workstream does **not**:

- Certify scientific truth or institutional efficacy
- Replace SCOPE reviewer identity, grant lifecycle, or signing
- Run general reinforcement learning or learn policy from pilot outcomes
- Authorize P7 fully autonomous scientific operators
- Weaken institutional fail-closed behavior for placeholder release signers

See ADRs under [`adr/`](adr/) and updates in [`limitations.md`](limitations.md) / [`threat_model.md`](threat_model.md).

## AS workstream checklist

| ID | Principal contract |
|----|--------------------|
| AS-00 | Baseline freeze + ADRs + non-claims |
| AS-01 | Global ID/digest bindings + VSA bundle checks |
| AS-02 | `stack_profile` validation CLI |
| AS-03 | `decision_basis` artifact |
| AS-04 | Uniform failure mapping |
| AS-05 | Five pilot modes + shadow isolation |
| AS-06 | SCOPE/PF/PCS binding hardening |
| AS-07 | Append-only outcome_ref + pilot metrics |
| AS-08 | `reconstruct` CLI + institutional pilot docs |
