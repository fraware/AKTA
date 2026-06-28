"""Tests for v0.6 inter-rater metadata in eval runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.inter_rater import (
    LABEL_SOURCE_INTER_RATER_CONSENSUS,
    LABEL_SOURCE_ORACLE_INDEPENDENT,
    attach_label_metadata,
    compute_inter_rater_stats,
    extract_label_metadata,
)
from evals.run_scenarios import run_scenario_eval

ROOT = Path(__file__).resolve().parent.parent


def test_extract_label_metadata_valid() -> None:
    meta = extract_label_metadata({
        "scenario_id": "s1",
        "admissibility": "blocked",
        "label_source": "inter_rater_consensus",
        "reviewer_ids": ["a", "b"],
        "inter_rater_agreement": 0.9,
    })
    assert meta is not None
    assert meta["label_source"] == LABEL_SOURCE_INTER_RATER_CONSENSUS
    assert meta["reviewer_ids"] == ["a", "b"]
    assert meta["inter_rater_agreement"] == 0.9


def test_extract_label_metadata_rejects_invalid_source() -> None:
    with pytest.raises(ValueError, match="Invalid label_source"):
        extract_label_metadata({
            "scenario_id": "s1",
            "label_source": "unknown_source",
        })


def test_compute_inter_rater_stats() -> None:
    results = [
        {
            "scenario_id": "a",
            "passed": True,
            "label_metadata": {
                "label_source": LABEL_SOURCE_ORACLE_INDEPENDENT,
                "inter_rater_agreement": 1.0,
            },
        },
        {
            "scenario_id": "b",
            "passed": True,
            "label_metadata": {
                "label_source": LABEL_SOURCE_INTER_RATER_CONSENSUS,
                "inter_rater_agreement": 0.85,
            },
        },
        {"scenario_id": "c", "passed": False},
    ]
    stats = compute_inter_rater_stats(results)
    assert stats["total_labeled"] == 2
    assert stats["total_unlabeled"] == 1
    assert stats["oracle_independent_count"] == 1
    assert stats["consensus_labeled_count"] == 1
    assert stats["mean_inter_rater_agreement"] == pytest.approx(0.925)
    assert stats["consensus_accuracy"] == 1.0


def test_run_scenario_eval_includes_inter_rater_stats() -> None:
    report = run_scenario_eval(
        ROOT / "scenarios" / "canonical_5.jsonl",
        ROOT / "scenarios" / "expected_decisions.jsonl",
        policy_dir=ROOT / "policy",
        overlays_dir=ROOT / "overlays",
    )
    assert "inter_rater_stats" in report
    stats = report["inter_rater_stats"]
    assert stats["total_labeled"] >= 1
    labeled = [r for r in report["results"] if r.get("label_metadata")]
    assert any(r["scenario_id"] == "canonical_2_protocol_drift" for r in labeled)
    canonical = next(r for r in labeled if r["scenario_id"] == "canonical_2_protocol_drift")
    assert canonical["label_metadata"]["label_source"] == "gate_derived"


def test_attach_label_metadata_omits_when_absent() -> None:
    result = attach_label_metadata({"scenario_id": "x", "passed": True}, {"scenario_id": "x"})
    assert "label_metadata" not in result


def test_public_100_inter_rater_coverage() -> None:
    report = run_scenario_eval(
        ROOT / "scenarios" / "public_100.jsonl",
        ROOT / "scenarios" / "expected_decisions.jsonl",
        policy_dir=ROOT / "policy",
        overlays_dir=ROOT / "overlays",
    )
    stats = report["inter_rater_stats"]
    assert stats["consensus_labeled_count"] >= 2
    assert stats["oracle_independent_count"] >= 1
    assert stats["mean_inter_rater_agreement"] is not None
