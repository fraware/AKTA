"""AKTA-Bench v1 corpus size and eval smoke tests."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _count_jsonl(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def test_oracle_corpus_size() -> None:
    assert _count_jsonl(ROOT / "scenarios" / "oracle_independent.jsonl") >= 100


def test_holdout_corpus_size() -> None:
    assert _count_jsonl(ROOT / "scenarios" / "holdout_private.jsonl") >= 30


def test_adversarial_corpus_size() -> None:
    assert _count_jsonl(ROOT / "scenarios" / "adversarial_transitions.jsonl") >= 30


def test_labtrust_imported_size() -> None:
    path = ROOT / "scenarios" / "labtrust_gym_imported.jsonl"
    if path.is_file():
        assert _count_jsonl(path) >= 50


def test_classifier_edge_cases_size() -> None:
    path = ROOT / "scenarios" / "classifier_edge_cases.jsonl"
    if path.is_file():
        assert _count_jsonl(path) >= 20


def test_inter_rater_metadata_coverage() -> None:
    rows = []
    for line in (ROOT / "scenarios" / "expected_decisions.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    with_meta = sum(1 for r in rows if r.get("inter_rater_agreement") is not None)
    assert with_meta / max(len(rows), 1) >= 0.8
