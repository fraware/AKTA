"""Tests for AKTAContext."""

from __future__ import annotations

import json
from pathlib import Path

from akta.context import AKTAContext

ROOT = Path(__file__).resolve().parent.parent


def test_from_file_loads_weak_evidence_context() -> None:
    ctx = AKTAContext.from_file(ROOT / "examples" / "weak_evidence" / "context.json")
    assert ctx.domain == "materials"
    assert ctx.evidence_state == "E2_preliminary_signal"


def test_to_dict_roundtrip() -> None:
    original = {
        "domain": "computational",
        "evidence_state": "E4_internally_consistent_evidence",
        "metadata": {"instrument": "sim-v1"},
    }
    ctx = AKTAContext.from_dict(original)
    restored = AKTAContext.from_dict(ctx.to_dict())
    assert restored.domain == "computational"
    assert restored.evidence_state == original["evidence_state"]
    assert restored.metadata == original["metadata"]


def test_from_file_invalid_json_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    try:
        AKTAContext.from_file(bad)
        raise AssertionError("expected JSON decode error")
    except json.JSONDecodeError:
        pass
