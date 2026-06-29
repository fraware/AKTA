# Public release verification (v1.0)

Use this checklist before tagging a public release of the AKTA reference implementation. AKTA is an open protocol with a reference kernel — not a safety certification.

## Prerequisites

```bash
pip install -e ".[dev,security]"
```

## Required (in-repo) — every PR

| Step | Command | Expected |
|------|---------|----------|
| Full CI | `make ci` | All pytest, evals, adversarial transitions, and integration demos pass |
| Canonical scenarios | `make eval-canonical` | 100% accuracy on `scenarios/canonical_5.jsonl` |
| Public benchmark | `make eval-public-100` | Report written to `evals/reports/public_100.json` |
| Oracle-independent | `make eval-oracle` | Hand-written labels pass |
| Holdout private | `make eval-holdout` | Holdout slice passes (labels not published) |
| Adversarial F01–F15 | `make eval-v06` | Per-class coverage in `evals/reports/adversarial_transitions.json` |
| Weak-evidence demo | `make demo-akta-weak-evidence` | Artifacts under `examples/integrated_weak_evidence/` |
| Protocol-drift demo | `make demo-akta-scope-protocol-drift` | Artifacts under `examples/integrated_protocol_drift/` |
| Reconstructable chain | `make demo-reconstructable` | Canonical chain under `dist/reconstructable_experiment/` |

## Required on release gate (SCOPE live) — PR + main

Set `SCOPE_REPO_PATH` to a SCOPE v0.9+ checkout, then:

| Step | Command | Expected |
|------|---------|----------|
| Fixture sync | `make sync-scope-fixtures` | Fixtures match live SCOPE contract |
| Cross-repo demo | `make demo-reconstructable-cross-repo` | Live chain under `dist/reconstructable_cross_repo/` |
| Cross-repo verify | `make verify-reconstructable-cross-repo` | All required artifacts present |
| Pilot bundle | `make demo-pilot-bundle` + `make verify-pilot-bundle` | Quality report `all_ok=true` when live SCOPE |
| Maintainer chain | `make ci-pilot` | Chains cross-repo + pilot verify |

Release gate CI (`.github/workflows/release-gate.yml`) runs SCOPE live verification, pilot bundle checks, AKTA-Bench v1 (`make eval-bench-v1`), and optional sibling matrix steps automatically. SCOPE uses the public clone URL when `SCOPE_REPO_URL` is not configured.

### Branch protection (main)

Require these GitHub Actions checks before merge:

| Check | Workflow job |
|-------|----------------|
| CI | `ci` |
| Release Gate — SCOPE live | `Release Gate / scope-live-gate` |
| Release Gate — Bench v1 | `Release Gate / eval-bench-v1` |

When sibling repository variables are configured, also require `Release Gate / sibling-live-matrix`. See [.github/CROSS_REPO_CI.md](../.github/CROSS_REPO_CI.md).

## Required on tag v* only

| Step | Command | Expected |
|------|---------|----------|
| AKTA-Bench v1 | `make eval-bench-v1` | Oracle 100%, holdout pass, behavioral smoke |
| Full v1.0 verifier | `make verify-v1-release` | All orchestrated steps pass |
| Pilot artifact | GitHub Release upload | `dist/pilot_bundle/` from release-gate workflow |

## Optional (cross-repo siblings)

Set repository variables per [.github/CROSS_REPO_CI.md](../.github/CROSS_REPO_CI.md):

- `PF_CORE_REPO_PATH` — PF runtime proof
- `PCS_CORE_REPO_PATH` — PCS bundle ingest
- `PCS_BENCH_REPO_PATH` — external benchmark harness
- `VSA_REPO_PATH` — VSA report validation
- `MEMORY_REPO_PATH` — Scientific Memory round-trip

## Production policy integrity smoke test

```bash
export AKTA_PRODUCTION_MODE=1
export AKTA_POLICY_HMAC_KEY="<deployment-secret>"
python scripts/regenerate_policy_manifest.py
akta gate --output examples/weak_evidence/ai_output.json \
  --tool lab_scheduler.prioritize \
  --profile P2_analysis_assistant \
  --context examples/weak_evidence/context.json \
  --out /tmp/akta_decision.json
```

Ed25519 release ceremony: see [policy_integrity.md](policy_integrity.md).

## Documentation sanity

- README distinguishes reference kernel, field benchmark v1, live trust stack, protocol v1.0
- [PROTOCOL_v1.0.md](PROTOCOL_v1.0.md) schema freeze declaration
- [limitations.md](limitations.md) states non-certification and authority boundary
- CHANGELOG includes the release version and date
- `pyproject.toml` version matches the tag

## Non-goals (do not block release on these)

- Live PF-Core or PCS-Core validation without sibling checkouts
- Operational deployment of P7 (permanently unsupported)
- Expert-reviewed institutional overlays beyond reference examples
