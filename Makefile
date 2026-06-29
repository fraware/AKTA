.PHONY: install test eval-canonical eval-public eval-public-100 eval-oracle eval-holdout eval-v06 eval-bench-v1 demo-weak-evidence demo-akta-weak-evidence demo-akta-scope-protocol-drift demo-reconstructable demo-reconstructable-cross-repo verify-reconstructable-cross-repo demo-pilot-bundle verify-pilot-bundle ci ci-pilot verify-v1-release sync-scope-fixtures import-labtrust-scenarios

PYTHON ?= python

install:
	$(PYTHON) -m pip install -e ".[dev,security]"

test:
	$(PYTHON) -m pytest tests/ skills/akta-scientific-action-admissibility/tests/ -v

eval-canonical:
	akta eval --scenarios scenarios/canonical_5.jsonl --expected scenarios/expected_decisions.jsonl --out evals/reports/canonical_5.json

eval-public-100:
	akta eval --scenarios scenarios/public_100.jsonl --expected scenarios/expected_decisions.jsonl --out evals/reports/public_100.json

eval-oracle:
	$(PYTHON) evals/run_oracle_independent.py --out evals/reports/oracle_independent.json

eval-holdout:
	$(PYTHON) evals/run_holdout_eval.py --out evals/reports/holdout_private.json

eval-v06:
	$(PYTHON) evals/adversarial_transitions.py --out evals/reports/adversarial_transitions.json

eval-bench-v1: eval-oracle eval-holdout eval-v06
	$(PYTHON) evals/behavioral_runner.py --out evals/reports/behavioral_v1.json
	$(PYTHON) -m pytest tests/test_eval_bench_v1.py -v

demo-reconstructable:
	$(PYTHON) scripts/demo_reconstructable_experiment.py

demo-reconstructable-cross-repo:
	$(PYTHON) -c "import os,sys; ok=bool(os.environ.get('SCOPE_REPO_PATH') or os.environ.get('SCOPE_CLI')); (print('Set SCOPE_REPO_PATH or SCOPE_CLI for live SCOPE') if not ok else None); sys.exit(0 if ok else 1)"
	$(PYTHON) scripts/demo_reconstructable_experiment.py --cross-repo

verify-reconstructable-cross-repo:
	$(PYTHON) scripts/verify_reconstructable_cross_repo.py

demo-pilot-bundle:
	$(PYTHON) scripts/generate_pilot_bundle.py

verify-pilot-bundle:
	$(PYTHON) scripts/verify_reconstructable_cross_repo.py --pilot-mode

sync-scope-fixtures:
	$(PYTHON) scripts/sync_scope_contract_fixtures.py

import-labtrust-scenarios:
	$(PYTHON) scripts/import_labtrust_scenarios.py

ci-pilot: sync-scope-fixtures demo-reconstructable-cross-repo verify-reconstructable-cross-repo demo-pilot-bundle verify-pilot-bundle

verify-v1-release:
	$(PYTHON) scripts/verify_v1_release.py

demo-weak-evidence:
	$(PYTHON) scripts/demo_weak_evidence.py

demo-akta-weak-evidence:
	$(PYTHON) scripts/demo_integrated_weak_evidence.py

demo-akta-scope-protocol-drift:
	$(PYTHON) scripts/demo_akta_scope_protocol_drift.py

ci: install test eval-canonical eval-public-100 eval-oracle eval-holdout eval-v06
	$(PYTHON) -m pytest tests/test_invalid_cases.py tests/integration/ tests/contracts/ -v
	$(PYTHON) scripts/demo_integrated_weak_evidence.py
	$(PYTHON) scripts/demo_akta_scope_protocol_drift.py
	$(PYTHON) scripts/demo_reconstructable_experiment.py
