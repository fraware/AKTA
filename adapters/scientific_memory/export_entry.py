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
    """Simulate import -> bounded read-back for Scientific Memory integration."""
    stored = dict(entry)
    read_back = {
        "entry_hash": stored.get("entry_hash"),
        "admissibility": stored.get("admissibility"),
        "bounded_claims": stored.get("bounded_claims", [])[:10],
        "admissibility_history": stored.get("admissibility_history", []),
        "source_record_id": stored.get("source_record_id"),
    }
    read_back["round_trip_ok"] = (
        read_back["admissibility"] == entry.get("admissibility")
        and read_back["entry_hash"] == entry.get("entry_hash")
    )
    return read_back
