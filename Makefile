.PHONY: install test eval-canonical eval-public eval-public-100 demo-weak-evidence demo-akta-weak-evidence ci

PYTHON ?= python

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest tests/ -v

eval-canonical:
	akta eval --scenarios scenarios/canonical_5.jsonl --expected scenarios/expected_decisions.jsonl --out evals/reports/canonical_5.json

eval-public:
	akta eval --scenarios scenarios/public_40.jsonl --expected scenarios/expected_decisions.jsonl --out evals/reports/public_40.json

eval-public-100:
	akta eval --scenarios scenarios/public_100.jsonl --expected scenarios/expected_decisions.jsonl --out evals/reports/public_100.json

demo-weak-evidence:
	$(PYTHON) scripts/demo_weak_evidence.py

demo-akta-weak-evidence:
	$(PYTHON) scripts/demo_integrated_weak_evidence.py

ci: install test eval-canonical eval-public-100
	$(PYTHON) -m pytest tests/test_invalid_cases.py tests/integration/ -v
	$(PYTHON) scripts/demo_integrated_weak_evidence.py
