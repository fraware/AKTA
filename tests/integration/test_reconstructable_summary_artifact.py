"""Integration test for reconstructable experiment summary artifact (v0.8)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def clean_out_dir(monkeypatch: pytest.MonkeyPatch) -> Path:
    from scripts.demo_reconstructable_experiment import DEFAULT_OUT_DIR

    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)
    monkeypatch.delenv("SCOPE_CLI", raising=False)
    if DEFAULT_OUT_DIR.exists():
        shutil.rmtree(DEFAULT_OUT_DIR)
    return DEFAULT_OUT_DIR


def test_reconstructable_summary_artifact(clean_out_dir: Path) -> None:
    from scripts.demo_reconstructable_experiment import run_demo

    code = run_demo(cross_repo=False)
    assert code == 0

    summary_path = clean_out_dir / "04_scope_review_summary.json"
    assert summary_path.is_file(), "Missing first-class SCOPE summary artifact"

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary.get("approved_scope") == "single_run_queue_priority"
    assert summary.get("requested_scope") == "single_run_queue_priority"
    assert summary.get("identity_assurance_level") in ("IAL0", "IAL1", "IAL2", "IAL3", "IAL4")
    assert summary.get("signing_assurance_level") in ("SAL0", "SAL1", "SAL2", "SAL3", "SAL4")
    assert isinstance(summary.get("allowed_tools"), list)
    assert isinstance(summary.get("blocked_tools"), list)

    pcs_summary = json.loads(
        (clean_out_dir / "10_pcs_bundle" / "scope_review_summary.json").read_text(encoding="utf-8")
    )
    assert pcs_summary["approved_scope"] == summary["approved_scope"]

    recon = (clean_out_dir / "reconstruction_report.md").read_text(encoding="utf-8")
    assert "summary.json" in recon.lower() or "scope_review_summary" in recon.lower()
    assert "summary.approved_scope" in recon
    assert "summary.requested_scope" in recon
    assert "identity_assurance_level" in recon
    assert "signing_assurance_level" in recon
    assert "allowed_tools" in recon
    assert "blocked_tools" in recon

    manifest = json.loads((clean_out_dir / "10_pcs_bundle" / "manifest.json").read_text(encoding="utf-8"))
    assert "scope_review_summary.json" in manifest.get("files", [])
