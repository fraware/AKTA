"""Contract tests for optional external PCS-Bench checkout integration."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from akta import AKTAGate
from adapters.pcs_bench.runner import load_scenarios, pcs_bench_repo, run_pcs_bench_suite

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_in_repo_runner_mode(gate: AKTAGate, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PCS_BENCH_REPO_PATH", raising=False)
    report = run_pcs_bench_suite(
        ROOT / "scenarios" / "canonical_5.jsonl",
        ROOT / "scenarios" / "expected_decisions.jsonl",
        gate=gate,
    )
    assert report["runner_mode"] == "in_repo"
    assert report["total"] == 5
    assert report["passed"] is True


def test_external_import_runner(tmp_path: Path, gate: AKTAGate, monkeypatch: pytest.MonkeyPatch) -> None:
    stub_repo = tmp_path / "pcs-bench-stub"
    stub_repo.mkdir()
    (stub_repo / "pcs_bench").mkdir()
    (stub_repo / "pcs_bench" / "__init__.py").write_text("", encoding="utf-8")
    (stub_repo / "pcs_bench" / "runners").mkdir()
    (stub_repo / "pcs_bench" / "runners" / "__init__.py").write_text("", encoding="utf-8")
    runner_code = '''
def run_akta_suite(scenarios_path, expected=None, gate=None):
    from pathlib import Path
    import json
    count = sum(1 for line in Path(scenarios_path).read_text(encoding="utf-8").splitlines() if line.strip())
    return {
        "suite_id": "external-stub",
        "total": count,
        "passed_count": count,
        "passed": True,
        "results": [],
        "external": True,
    }
'''
    (stub_repo / "pcs_bench" / "runners" / "akta.py").write_text(runner_code, encoding="utf-8")
    monkeypatch.setenv("PCS_BENCH_REPO_PATH", str(stub_repo))

    report = run_pcs_bench_suite(
        ROOT / "scenarios" / "canonical_5.jsonl",
        gate=gate,
    )
    assert report["runner_mode"] == "external_import"
    assert report["external"] is True
    assert report["total"] == 5


def test_invalid_repo_path_falls_back_to_in_repo(gate: AKTAGate, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PCS_BENCH_REPO_PATH", "/nonexistent/pcs-bench-path")
    report = run_pcs_bench_suite(
        ROOT / "scenarios" / "canonical_5.jsonl",
        gate=gate,
    )
    assert report["runner_mode"] == "in_repo"
    assert report["total"] == 5


def test_pcs_bench_repo_helper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PCS_BENCH_REPO_PATH", str(tmp_path))
    assert pcs_bench_repo() == tmp_path
    monkeypatch.delenv("PCS_BENCH_REPO_PATH", raising=False)
    assert pcs_bench_repo() is None


def test_load_scenarios_round_trip(gate: AKTAGate) -> None:
    scenarios = load_scenarios(
        ROOT / "scenarios" / "canonical_5.jsonl",
        ROOT / "scenarios" / "expected_decisions.jsonl",
    )
    assert len(scenarios) == 5
    assert scenarios[0].scenario_id.startswith("canonical_")
