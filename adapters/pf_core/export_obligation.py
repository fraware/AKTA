"""Export PF-Core runtime obligation from AKTA Record."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_pf_obligation(record: dict[str, Any]) -> dict[str, Any]:
    """Build PF-Core obligation JSON from an AKTA Record."""
    decision = record.get("decision", {})
    provenance = record.get("provenance", {})
    return {
        "obligation_type": "tool_block" if decision.get("admissibility") in ("blocked", "abstain_insufficient_context") else "tool_allow",
        "source": "AKTA",
        "source_record_id": record.get("record_id"),
        "blocked_tools": decision.get("blocked_tools", []),
        "allowed_tools": decision.get("allowed_tools", []),
        "policy_hash": provenance.get("policy_hash"),
        "decision": decision.get("admissibility"),
        "next_admissible_steps": decision.get("next_admissible_steps", []),
        "required_review_role": decision.get("required_review_role"),
    }


def export_pf_obligation(record: Any, out_dir: str | Path) -> Path:
    """Write PF-Core obligation to output directory."""
    from akta.records import AKTARecord

    data = record.data if isinstance(record, AKTARecord) else record
    obligation = build_pf_obligation(data)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record_id = data.get("record_id", "unknown")
    path = out_dir / f"pf_obligation_{record_id}.json"
    path.write_text(json.dumps(obligation, indent=2), encoding="utf-8")
    return path
