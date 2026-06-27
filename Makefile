.PHONY: install test eval-canonical eval-public demo-weak-evidence ci

PYTHON ?= python

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest tests/ -v

eval-canonical:
	akta eval --scenarios scenarios/canonical_5.jsonl --expected scenarios/expected_decisions.jsonl --out evals/reports/canonical_5.json

eval-public:
	akta eval --scenarios scenarios/public_40.jsonl --expected scenarios/expected_decisions.jsonl --out evals/reports/public_40.json

demo-weak-evidence:
	$(PYTHON) scripts/demo_weak_evidence.py

ci: install test eval-canonical eval-public
	$(PYTHON) -m pytest tests/test_invalid_cases.py -v
