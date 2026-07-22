"""Integration test for frozen pilot bundle structure (AKTA-4)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.generate_pilot_bundle import PILOT_ARTIFACTS, run_pilot_bundle


@pytest.fixture
def clean_pilot_dir(monkeypatch: pytest.MonkeyPatch) -> Path:
    from scripts.generate_pilot_bundle import PILOT_OUT_DIR

    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)
    monkeypatch.delenv("SCOPE_CLI", raising=False)
    if PILOT_OUT_DIR.exists():
        shutil.rmtree(PILOT_OUT_DIR)
    return PILOT_OUT_DIR


def test_pilot_bundle_structure(clean_pilot_dir: Path) -> None:
    code = run_pilot_bundle(require_live_scope=False)
    assert code == 0

    for name in PILOT_ARTIFACTS:
        assert (clean_pilot_dir / name).exists(), f"Missing pilot artifact: {name}"

    quality = json.loads((clean_pilot_dir / "14_quality_report.json").read_text(encoding="utf-8"))
    assert quality["pilot_bundle_version"] == "akta-pilot-v1.0"
    assert "checks" in quality
    assert quality.get("identity_assurance_level") in ("IAL0", "IAL1", "IAL2", "IAL3", "IAL4")
    assert quality.get("signing_assurance_level") in ("SAL0", "SAL1", "SAL2", "SAL3", "SAL4")

    recon = (clean_pilot_dir / "reconstruction_report.md").read_text(encoding="utf-8")
    assert "contract_version" in recon.lower()

    manifest = json.loads(
        (clean_pilot_dir / "11_pcs_bundle" / "manifest.json").read_text(encoding="utf-8")
    )
    assert "scope_review_summary.json" in manifest.get("files", [])
