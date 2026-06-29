"""VSA live contract validation (v1.0)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_vsa_report_akta_schema() -> None:
    from adapters.vsa.import_report import validate_vsa_report

    report_path = ROOT / "examples" / "reconstructable_experiment" / "pcs_bundle" / "vsa_report.json"
    if not report_path.is_file():
        report_path = ROOT / "examples" / "integrated_weak_evidence" / "vsa_report.json"
    if not report_path.is_file():
        pytest.skip("VSA report fixture not available")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    validate_vsa_report(report)


@pytest.mark.integration
def test_vsa_sibling_validate_report() -> None:
    import os
    import sys

    vsa_repo = os.environ.get("VSA_REPO_PATH", "").strip()
    if not vsa_repo or not Path(vsa_repo).is_dir():
        pytest.skip("VSA_REPO_PATH not set")

    report_path = ROOT / "examples" / "reconstructable_experiment" / "pcs_bundle" / "vsa_report.json"
    if not report_path.is_file():
        pytest.skip("VSA report fixture not available")
    report = json.loads(report_path.read_text(encoding="utf-8"))

    src = Path(vsa_repo) / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from vsa.validate.engine import validate_report
        validate_report(report)
    except ImportError:
        pytest.skip("VSA validate_report not importable")
