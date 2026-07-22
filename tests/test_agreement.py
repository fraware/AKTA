"""Agreement metric scaffolding tests (synthetic fixtures only)."""

from __future__ import annotations

import json
from pathlib import Path

from evals.agreement import (
    agreement_report_from_synthetic_fixture,
    cohens_kappa,
    fleiss_kappa,
    krippendorff_alpha_nominal,
)

ROOT = Path(__file__).resolve().parent.parent


def test_cohens_kappa_perfect() -> None:
    assert cohens_kappa(["a", "b", "a"], ["a", "b", "a"]) == 1.0


def test_fleiss_and_krippendorff_smoke() -> None:
    matrix = [
        ["blocked", "blocked", "blocked"],
        ["allowed", "allowed", "review_required"],
    ]
    assert isinstance(fleiss_kappa(matrix), float)
    assert isinstance(krippendorff_alpha_nominal(matrix), float)


def test_synthetic_fixture_report() -> None:
    fixture = json.loads(
        (ROOT / "evals" / "fixtures" / "synthetic_inter_rater.json").read_text(encoding="utf-8")
    )
    report = agreement_report_from_synthetic_fixture(fixture)
    assert report["synthetic"] is True
    assert "cohens_kappa" in report
    assert "fleiss_kappa" in report
