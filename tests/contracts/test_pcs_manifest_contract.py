"""PCS manifest contract tests with pinned fixtures (v0.4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from adapters.pcs.export_artifact import export_pcs_bundle
from akta.records import AKTARecord, validate_against_schema

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_pcs_manifest_includes_v03_review_trigger(tmp_path: Path) -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Update active protocol threshold."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_threshold",
        context=AKTAContext.from_dict({
            "evidence_state": "E4_internally_consistent_evidence",
            "validation_status": "V3_preliminary_experimental_support",
        }),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
    )
    d = decision.to_dict()
    record = decision.to_record().to_dict()
    record["review_trigger"] = d["review_trigger"]
    out = export_pcs_bundle(AKTARecord(record), tmp_path / "pcs", decision=d, validate=True)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    validate_against_schema(manifest, "pcs_akta_artifact.schema.json")
    assert "review_trigger.json" in manifest["files"]
    trigger = json.loads((out / "review_trigger.json").read_text(encoding="utf-8"))
    assert trigger["requested_scope"] == "active_protocol_update"
    assert trigger["review_trigger_version"] == "0.3"


def test_pcs_pinned_fixture_full_shape() -> None:
    manifest = json.loads((FIXTURES / "pcs_manifest_v0.4.json").read_text(encoding="utf-8"))
    manifest["schema_version"] = "akta-record-v0.5"
    manifest["file_hashes"] = {f: f"sha256:{'0' * 64}" for f in manifest["files"] if f != "manifest.json"}
    validate_against_schema(manifest, "pcs_akta_artifact.schema.json")
    assert manifest["artifact_type"] == "akta_scientific_action_record"
    assert "review_trigger.json" in manifest["files"]
    assert manifest["schema_version"] == "akta-record-v0.5"
    for field in (
        "record_hash",
        "policy_hash",
        "tool_registry_hash",
        "domain_overlay_hash",
        "decision_id",
        "manifest_hash",
    ):
        assert manifest.get(field), f"missing {field}"
