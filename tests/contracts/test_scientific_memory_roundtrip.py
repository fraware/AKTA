"""Scientific Memory round-trip contract test (v1.0)."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_memory_export_round_trip_local() -> None:
    from adapters.scientific_memory.export_entry import export_entry_from_bundle, round_trip_entry

    bundle = ROOT / "examples" / "integrated_protocol_drift" / "pcs_bundle"
    if not bundle.is_dir():
        pytest.skip("PCS bundle fixture not available")
    entry = export_entry_from_bundle(bundle)
    read_back = round_trip_entry(entry)
    assert read_back["round_trip_ok"] is True
    assert read_back["admissibility"] == entry["admissibility"]


@pytest.mark.integration
def test_memory_sibling_round_trip() -> None:
    import os

    memory_repo = os.environ.get("MEMORY_REPO_PATH", "").strip()
    if not memory_repo or not Path(memory_repo).is_dir():
        pytest.skip("MEMORY_REPO_PATH not set")

    from adapters.scientific_memory.export_entry import export_entry_from_bundle, round_trip_entry

    bundle = ROOT / "examples" / "integrated_protocol_drift" / "pcs_bundle"
    entry = export_entry_from_bundle(bundle)
    read_back = round_trip_entry(entry)
    assert read_back["round_trip_ok"]
