# AKTA-Bench dual-product shape (directive §8)

AKTA-Bench has two distinct products. Do not conflate them.

## 1. Protocol-conformance suite

- Entrypoint: `python -m evals.protocol_conformance`
- Ground truth: policy-expected decisions (`scenarios/expected_decisions.jsonl`)
- Purpose: regression / release-gate conformance of the reference kernel
- Not empirical human performance evidence
- **Not** a measure of helpful boundedness

## 2. Empirical impact benchmark (P1-D)

- Entrypoint: `python -m evals.empirical_impact`
- Protocol artifacts: `evals/empirical/preregistration.json`, `study_protocol.json`
- Ground truth: independent domain annotations (or clearly marked synthetic fixtures for CI)
- Agreement scaffolding: `evals/agreement.py` (Cohen’s κ; Fleiss / Krippendorff hooks)
- Synthetic fixture: `evals/fixtures/synthetic_inter_rater.json` (`synthetic: true`)
- Helpful boundedness is preregistered mathematically (`HB = |A ∩ B| / |A ∪ B|`) **before**
  observing results; see `HelpfulBoundednessDefinition` in `evals/empirical_impact.py`
- Cost-sensitive companion uses **class-specific loss weights** (`CostHB = HB − Σ w_c·Spill_c`), not a single λ
- `preregistration.json` is an **immutable signed artifact** (P1-16); CI verifies hash/signature and never rewrites it
- Amendments require parent hash, reason, changed fields, approval, signature, and a timestamp before observations (`evals/empirical/amendment.schema.json`)
- **Do not** treat developer policy outputs as empirical ground truth
- **Do not** claim helpful boundedness from policy-conformance accuracy alone
- Preserve raw annotation schema fields in fixtures; do not invent fake reviewer identities as if real
- `--dry-run` executes a synthetic harness with `empirical_complete=false`

## Agreement metrics

```bash
python -m evals.preregistration_lock
python -m evals.empirical_impact --dry-run --write-protocol
python -m pytest tests/test_agreement.py tests/test_empirical_impact.py tests/test_preregistration_verification.py -q
```
