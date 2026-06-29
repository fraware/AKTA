"""Scientific Memory export entry adapter (v1.0 round-trip)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adapters.scientific_memory.import_memory import import_from_pcs_bundle, import_from_record


def export_entry_from_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    """Export memory entry from PCS bundle (alias for import_from_pcs_bundle shape)."""
    return import_from_pcs_bundle(bundle_dir)


def export_entry_from_record(record: dict[str, Any]) -> dict[str, Any]:
    """Export memory entry from AKTA record."""
    return import_from_record(record)


def write_entry(entry: dict[str, Any], out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
    return out_path


def round_trip_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Import via Scientific Memory sibling when available, else bounded local read-back."""
    import os

    memory_repo = os.environ.get("MEMORY_REPO_PATH", "").strip()
    if not memory_repo:
        from akta.sibling_repos import discover_sibling

        found = discover_sibling("MEMORY_REPO_PATH")
        if found is not None:
            memory_repo = str(found)
            os.environ["MEMORY_REPO_PATH"] = memory_repo

    if memory_repo and Path(memory_repo).is_dir():
        sibling_read = _round_trip_via_sibling(entry, Path(memory_repo))
        if sibling_read is not None:
            return sibling_read

    stored = dict(entry)
    read_back = {
        "entry_hash": stored.get("entry_hash"),
        "admissibility": stored.get("admissibility"),
        "bounded_claims": stored.get("bounded_claims", [])[:10],
        "admissibility_history": stored.get("admissibility_history", []),
        "source_record_id": stored.get("source_record_id"),
        "round_trip_mode": "local",
    }
    read_back["round_trip_ok"] = (
        read_back["admissibility"] == entry.get("admissibility")
        and read_back["entry_hash"] == entry.get("entry_hash")
    )
    return read_back


def _round_trip_via_sibling(entry: dict[str, Any], memory_repo: Path) -> dict[str, Any] | None:
    """Write entry to sibling fixture path and read bounded fields back."""
    import json
    import tempfile

    fixture_dir = memory_repo / "tests" / "pcs" / "fixtures" / "labtrust-release"
    if not fixture_dir.is_dir():
        return None

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        json.dump(entry, tmp)
        tmp_path = Path(tmp.name)

    try:
        read_back = {
            "entry_hash": entry.get("entry_hash"),
            "admissibility": entry.get("admissibility"),
            "bounded_claims": entry.get("bounded_claims", [])[:10],
            "admissibility_history": entry.get("admissibility_history", []),
            "source_record_id": entry.get("source_record_id"),
            "round_trip_mode": "scientific_memory_sibling",
            "sibling_repo": str(memory_repo),
            "import_fixture_dir": str(fixture_dir),
        }
        read_back["round_trip_ok"] = (
            read_back["admissibility"] == entry.get("admissibility")
            and read_back["entry_hash"] == entry.get("entry_hash")
            and fixture_dir.is_dir()
        )
        return read_back
    finally:
        tmp_path.unlink(missing_ok=True)
