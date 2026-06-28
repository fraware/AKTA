.PHONY: install test eval-canonical eval-public eval-public-100 eval-oracle demo-weak-evidence demo-akta-weak-evidence demo-akta-scope-protocol-drift ci

PYTHON ?= python

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest tests/ skills/akta-scientific-action-admissibility/tests/ -v

eval-canonical:
	akta eval --scenarios scenarios/canonical_5.jsonl --expected scenarios/expected_decisions.jsonl --out evals/reports/canonical_5.json

eval-public-100:
	akta eval --scenarios scenarios/public_100.jsonl --expected scenarios/expected_decisions.jsonl --out evals/reports/public_100.json

eval-oracle:
	$(PYTHON) evals/run_oracle_independent.py --out evals/reports/oracle_independent.json

demo-weak-evidence:
	$(PYTHON) scripts/demo_weak_evidence.py

demo-akta-weak-evidence:
	$(PYTHON) scripts/demo_integrated_weak_evidence.py

demo-akta-scope-protocol-drift:
	$(PYTHON) scripts/demo_akta_scope_protocol_drift.py

ci: install test eval-canonical eval-public-100 eval-oracle
	$(PYTHON) -m pytest tests/test_invalid_cases.py tests/integration/ tests/contracts/ -v
	$(PYTHON) scripts/demo_integrated_weak_evidence.py
	$(PYTHON) scripts/demo_akta_scope_protocol_drift.py
