# Holdout private governance

AKTA maintains a private holdout slice (`scenarios/holdout_private.jsonl`) for credibility checks outside the public 100-scenario benchmark.

## Purpose

- Detect overfitting to public scenarios
- Validate behavioral expectations (tool allow/block) not visible in public labels
- Gate release acceptance without publishing holdout labels

## Access

Holdout expected admissibility labels are embedded in `evals/run_holdout_eval.py` (`HOLDOUT_EXPECTED`) for CI only. Do not copy holdout labels into public documentation or training corpora.

## Running holdout eval

```bash
python evals/run_holdout_eval.py --out evals/reports/holdout_private.json
make eval-holdout
```

## Governance rules

1. Holdout scenarios are not included in `public_100.jsonl` accuracy marketing without holdout disclosure.
2. Changes to holdout scenarios require maintainer review; version holdout changes in CHANGELOG.
3. Inter-rater metadata on public scenarios does not apply to holdout rows unless explicitly labeled.
4. Failure class coverage for high-risk F01/F05/F06/F08/F14 must include holdout or adversarial positive controls.

## CI

`make ci` runs holdout eval. Failure blocks release acceptance.
