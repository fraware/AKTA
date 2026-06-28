# Public release verification (v0.7.1)

Use this checklist before tagging a public release of the AKTA reference implementation. AKTA is an open protocol with a reference kernel — not a safety certification.

## Prerequisites

```bash
pip install -e ".[dev,security]"
```

## Required (in-repo)

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

## Optional (live SCOPE sibling)

When a SCOPE v0.5+ checkout is available:

```bash
# python-import
SCOPE_REPO_PATH=/path/to/SCOPE python scripts/verify_scope_live_chain.py --mode python-import

# three-step CLI
SCOPE_CLI=scope python scripts/verify_scope_live_chain.py --mode cli

# unified akta review CLI
SCOPE_CLI=scope SCOPE_CLI_MODE=akta-review python scripts/verify_scope_live_chain.py --mode akta-review
```

The verifier must report `adapter_mode=python-import`, `cli`, or `akta-review-cli` — never `simulated`.

## Optional (cross-repo siblings)

Set repository variables per [.github/CROSS_REPO_CI.md](../.github/CROSS_REPO_CI.md), then:

```bash
pytest tests/contracts/ tests/integration/ -v -m integration
```

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

Experimental domain overlays (biology, chemistry, clinical) must be refused in production mode.

## Documentation sanity

- README acceptance tables include v0.7.1 through v0.1
- [limitations.md](limitations.md) states non-certification and authority boundary
- CHANGELOG includes the release version and date
- `pyproject.toml` version matches the tag

## Non-goals (do not block release on these)

- Live PF-Core or PCS-Core validation without sibling checkouts
- Operational deployment of P7 (permanently unsupported)
- Expert-reviewed institutional overlays beyond reference examples
