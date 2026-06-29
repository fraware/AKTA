"""PCS-Core live bundle ingest contract test (v1.0)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def pilot_pcs_bundle() -> Path:
    bundle = ROOT / "examples" / "integrated_protocol_drift" / "pcs_bundle"
    if not bundle.is_dir():
        pytest.skip("PCS bundle fixture not available")
    return bundle


def test_pcs_bundle_local_validation(pilot_pcs_bundle: Path) -> None:
    from adapters.pcs.export_artifact import validate_pcs_bundle

    validate_pcs_bundle(pilot_pcs_bundle)


@pytest.mark.integration
def test_pcs_core_live_ingest(pilot_pcs_bundle: Path) -> None:
    from tests.contracts.cross_repo_helpers import validate_pcs_bundle_live

    skip = validate_pcs_bundle_live(pilot_pcs_bundle)
    if skip and "not set" in skip:
        pytest.skip(skip)
    manifest = json.loads((pilot_pcs_bundle / "manifest.json").read_text(encoding="utf-8"))
    assert "akta_record.json" in (manifest.get("files") or [])
