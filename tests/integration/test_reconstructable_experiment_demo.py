"""Integration test for reconstructable experiment demo (v0.8)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent

EXPECTED_ARTIFACTS = [
    "00_vsa_report.json",
    "01_akta_decision.json",
    "02_akta_record.json",
    "03_review_trigger.json",
    "04_scope_review_summary.json",
    "05_scope_packet.json",
    "06_scope_decision.json",
    "07_scope_grant.json",
    "08_pf_obligation.json",
    "09_pf_trace_certificate.json",
    "10_pcs_bundle",
    "11_scientific_memory_import.json",
    "12_pcs_bench_report.json",
    "01_akta_decision_after_grant.json",
    "README.md",
    "reconstruction_report.md",
]


@pytest.fixture
def clean_out_dir(monkeypatch: pytest.MonkeyPatch) -> Path:
    from scripts.demo_reconstructable_experiment import DEFAULT_OUT_DIR

    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)
    monkeypatch.delenv("SCOPE_CLI", raising=False)
    if DEFAULT_OUT_DIR.exists():
        shutil.rmtree(DEFAULT_OUT_DIR)
    return DEFAULT_OUT_DIR


def test_reconstructable_experiment_demo_generates_chain(
    clean_out_dir: Path,
) -> None:
    from scripts.demo_reconstructable_experiment import run_demo

    code = run_demo(cross_repo=False)
    assert code == 0

    for name in EXPECTED_ARTIFACTS:
        path = clean_out_dir / name
        assert path.exists(), f"Missing artifact: {name}"

    manifest = json.loads((clean_out_dir / "10_pcs_bundle" / "manifest.json").read_text(encoding="utf-8"))
    record = json.loads((clean_out_dir / "02_akta_record.json").read_text(encoding="utf-8"))
    assert manifest.get("record_hash") == record.get("record_hash")
    assert manifest.get("integrity_mode") in (
        None,
        "dev_unsigned",
        "deployment_hmac_attested",
        "release_ed25519_signed",
    )
    assert "scope_review_summary.json" in manifest.get("files", [])

    recon = (clean_out_dir / "reconstruction_report.md").read_text(encoding="utf-8")
    assert "linkage" in recon.lower() or "Linkage" in recon
    assert "Case C" in recon or "post-grant" in recon.lower()
    assert "summary" in recon.lower()

    post_grant = json.loads(
        (clean_out_dir / "01_akta_decision_after_grant.json").read_text(encoding="utf-8")
    )
    assert post_grant["admissibility"] in ("blocked", "review_required", "authorization_required")
    assert post_grant["admissibility"] not in ("allowed", "allowed_with_logging", "draft_only")
