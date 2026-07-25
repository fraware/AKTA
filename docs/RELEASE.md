# Public release verification (v1.2 + AS hardening)

Use this checklist before tagging a public release of the AKTA reference implementation (`akta-protocol` **1.2.0** plus Admissibility-Stack hardening). AKTA is an open protocol with a reference kernel — not a safety certification.

## Admissibility-Stack acceptance matrix (AS-00–08)

| Criterion | Command / evidence |
|-----------|-------------------|
| Reconstructable decisions | `akta reconstruct --release action_release/ --out reconstruction.json`; AS-01/03/08 tests |
| Pilot mode restrictions | `pytest tests/test_as05_pilot_modes.py`; shadow `operational_influence=false` |
| SCOPE/PF/PCS bindings | `pytest tests/test_as06_bindings_chain.py` |
| Append-only outcomes | `pytest tests/test_as07_outcome_metrics.py`; `akta link-outcome` |
| Privacy-preserving metrics | `akta export-pilot-metrics`; schema forbids raw evidence/PII fields |
| Refuse unsupported autonomous ops | ADR 0001 non-claims + mode allowlists + existing abstain/block |
| Benchmark backward compatibility | `make eval-bench-v1` / public_100 expectations unchanged |

### Reconstruction release checklist

1. Clean checkout at declared base commit (`docs/as_baseline.md`)
2. `make install` && `make ci`
3. Build action release / PCS bundle
4. `akta reconstruct --release … --out reconstruction.json` → `ok=true`
5. Record bundle checksums from reconstruction report

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
| Full sibling matrix | Release-gate `sibling-live-matrix` | PF, PCS-Core, PCS-Bench, VSA clone, Memory all present |
| Release evidence | `python scripts/build_release_evidence_report.py` | `dist/release_evidence.json` with commits, hashes, SBOM, audit, CodeQL stub |
| Pilot artifact | GitHub Release upload | `dist/pilot_bundle/` from release-gate workflow |
| Wheel reproducibility | CI package job | Digests match under `SOURCE_DATE_EPOCH`, or documented normalization token |

VSA is pinned to tag `v0.7.2` (`903d834f201535ac1525e3e8907254363209904f`) from
https://github.com/fraware/verified-science-agent.git. Institutional release still
fail-closes on a missing VSA checkout or `git rev-parse HEAD` mismatch.

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

## Hash-linked release / pilot artifact chain

Pilot and reconstructable demos should emit a hash-linked chain. Components that exist today:

| Artifact | Generator / verifier |
|----------|----------------------|
| Decision + Record + policy binding | `akta` gate / `effective_policy_manifest.json` |
| SCOPE review summary | reconstructable demos / SCOPE adapter |
| PCS bundle | `adapters/pcs/export_artifact.py` |
| Pilot bundle `00`–`14` | `scripts/generate_pilot_bundle.py` |
| Chain verify | `scripts/verify_reconstructable_cross_repo.py` |

### Sibling-dependent checks (optional until env configured)

These do not block in-repo `make ci`. They require sibling checkouts:

- Live SCOPE grant signatures and non-simulated summaries (`SCOPE_REPO_PATH` or `SCOPE_CLI`)
- PF-Core obligation export live proof (`PF_CORE_REPO_PATH`)
- PCS-Core ingest attestation (`PCS_CORE_REPO_PATH`)

In-repo demos still write local hash linkages under `dist/` (gitignored; regenerate with Makefile targets). Release gate fails closed when SCOPE CLI is mandatory and missing.

Ed25519 release ceremony: see [policy_integrity.md](policy_integrity.md).

## Documentation sanity

- README distinguishes reference kernel, field benchmark v1, live trust stack, protocol v1.0, and AS hardening docs
- [PROTOCOL_v1.0.md](PROTOCOL_v1.0.md) schema freeze declaration (AS fields are additive/optional)
- [limitations.md](limitations.md) and ADRs (`adr/0001`–`0003`) state non-claims and authority boundary
- [operator_pilot_guide.md](operator_pilot_guide.md) / [reviewer_pilot_guide.md](reviewer_pilot_guide.md) match CLI (`gate --mode`, `reconstruct`, `link-outcome`, `export-pilot-metrics`, `validate-stack-profile`)
- CHANGELOG includes the release version and AS hardening notes
- `pyproject.toml` version matches the tag (`1.2.0` at baseline)

## Non-goals (do not block release on these)

- Live PF-Core or PCS-Core validation without sibling checkouts
- Operational deployment of P7 (permanently unsupported)
- Expert-reviewed institutional overlays beyond reference examples
