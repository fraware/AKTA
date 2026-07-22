# AKTA-Bench dual-product shape (directive §8)

AKTA-Bench has two distinct products. Do not conflate them.

## 1. Protocol-conformance suite

- Entrypoint: `python -m evals.protocol_conformance`
- Ground truth: policy-expected decisions (`scenarios/expected_decisions.jsonl`)
- Purpose: regression / release-gate conformance of the reference kernel
- Not empirical human performance evidence

## 2. Empirical impact benchmark

- Entrypoint: `python -m evals.empirical_impact`
- Ground truth: independent domain annotations (or clearly marked synthetic fixtures for CI)
- Agreement scaffolding: `evals/agreement.py` (Cohen’s κ; Fleiss / Krippendorff hooks)
- Synthetic fixture: `evals/fixtures/synthetic_inter_rater.json` (`synthetic: true`)
- **Do not** treat developer policy outputs as empirical ground truth
- Preserve raw annotation schema fields in fixtures; do not invent fake reviewer identities as if real

## Agreement metrics

```bash
python -m evals.empirical_impact
python -m pytest tests/test_agreement.py -q
```
