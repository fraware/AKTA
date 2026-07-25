# Contributing to AKTA

Thank you for contributing to the Open Scientific Action Protocol.

## Development setup

```bash
git clone https://github.com/fraware/AKTA.git
cd AKTA
pip install -e ".[dev,security]"
pytest tests/ -v
```

Full local gate: `make ci`. Do not commit regenerable `dist/` outputs, `__pycache__/`, or Hypothesis caches (see `.gitignore`).

## Pull request guidelines

1. Keep changes focused on scientific action admissibility — avoid scope creep into evidence retrieval, proof kernels, or release packaging.
2. All policy and schema changes must include updated tests.
3. Run `pytest tests/ -v` and `akta eval --scenarios scenarios/canonical_5.jsonl --expected scenarios/expected_decisions.jsonl` before submitting. For AS surfaces, also run `pytest tests/test_as*.py -v`.
4. Do not add operational bio/chem protocol examples without domain expert review.
5. Follow existing naming conventions for action types (A0–A10), responsibility levels (R0–R9), and deployment profiles (P0–P6).
6. Disambiguate **PilotMode** (`akta gate --mode`) from REST deployment `--mode` and legacy `PilotStage` aliases. Preserve ADR non-claims (admissibility is not truth certification; pilot metrics are not efficacy scores).

## Policy changes

Policy files live in `policy/` and `overlays/`. Changes require:

- Updated hashes reflected in test fixtures
- Documentation in `docs/` when behavior changes
- Scenario updates when acceptance criteria shift

## Code of conduct

Be respectful, precise, and evidence-oriented. AKTA governs claim-to-action transitions — contributions should preserve that boundary. See [GOVERNANCE.md](GOVERNANCE.md) and [docs/adr/0001-admissibility-boundary.md](docs/adr/0001-admissibility-boundary.md).
