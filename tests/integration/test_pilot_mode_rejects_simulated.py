"""Pilot mode verifier rejects simulated adapter (AKTA-2)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def simulated_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)
    monkeypatch.delenv("SCOPE_CLI", raising=False)
    from scripts.demo_reconstructable_experiment import run_demo

    out = tmp_path / "simulated_bundle"
    monkeypatch.setattr("scripts.demo_reconstructable_experiment.DEFAULT_OUT_DIR", out)
    monkeypatch.setattr("scripts.demo_reconstructable_experiment.CROSS_REPO_OUT_DIR", out)
    code = run_demo(cross_repo=False)
    assert code == 0
    return out


def test_pilot_mode_rejects_simulated_adapter(simulated_bundle: Path) -> None:
    from scripts.verify_reconstructable_cross_repo import verify

    assert verify(simulated_bundle, pilot_mode=True) == 1


def test_pilot_mode_requires_ial_and_sal(simulated_bundle: Path) -> None:
    summary_path = simulated_bundle / "04_scope_review_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary.get("identity_assurance_level")
    assert summary.get("signing_assurance_level")

    summary.pop("identity_assurance_level", None)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    from scripts.verify_reconstructable_cross_repo import verify

    assert verify(simulated_bundle, pilot_mode=True) == 1


def test_pilot_mode_rejects_synthetic_without_provenance(simulated_bundle: Path) -> None:
    summary_path = simulated_bundle / "04_scope_review_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary.get("summary_origin") == "akta_simulated"

    from scripts.verify_reconstructable_cross_repo import verify

    assert verify(simulated_bundle, pilot_mode=True) == 1
