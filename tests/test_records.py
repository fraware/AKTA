"""Tests for AKTA Record generation."""

import json
from pathlib import Path

from akta import AKTAGate, AKTAContext
from akta.records import validate_against_schema

ROOT = Path(__file__).resolve().parent.parent


def test_decision_to_record() -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    ctx = AKTAContext.from_dict({
        "domain": "materials",
        "evidence_state": "E2_preliminary_signal",
        "project_id": "demo",
    })
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize condition B."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_next_run",
        context=ctx,
        deployment_profile="P2_analysis_assistant",
        domain_overlay="generic_lab_v0",
    )
    record = decision.to_record(ai_output={"summary": "Prioritize condition B."}, context=ctx.to_dict())
    data = record.to_dict()
    assert data["record_type"] == "scientific_action_record"
    assert data["record_hash"].startswith("sha256:")
    assert data["provenance"]["policy_hash"].startswith("sha256:")
    validate_against_schema(data, "akta_record.schema.json")


def test_record_save_and_load(tmp_path: Path) -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output="Explain photosynthesis.",
        requested_tool="literature_search.query",
        requested_action="explain",
        context=AKTAContext.from_dict({"evidence_state": "E0_no_evidence"}),
        deployment_profile="P0_no_action_assistant",
    )
    record = decision.to_record()
    out = tmp_path / "record.json"
    record.save(out)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["record_id"] == record.to_dict()["record_id"]
