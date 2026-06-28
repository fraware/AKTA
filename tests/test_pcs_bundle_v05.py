"""PCS v0.5 full-chain export and tamper detection tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from adapters.pcs.export_artifact import export_pcs_bundle, validate_pcs_bundle
from akta.records import AKTARecord, validate_against_schema

ROOT = Path(__file__).resolve().parent.parent


def _review_required_bundle(tmp_path: Path) -> Path:
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

    scope_packet = {"packet_type": "scope_review_packet", "trigger": {"requested_scope": "active_protocol_update"}}
    scope_decision = {"status": "granted", "granted_scope": "protocol_draft"}
    scope_grant = {
        "grant_id": "SCOPE-GRANT-TEST",
        "granted_scope": "protocol_draft",
        "requested_scope": "active_protocol_update",
    }
    pf_obligation = {"obligation_type": "tool_review", "obligation_id": "PF-OBL-TEST"}

    out = tmp_path / "pcs"
    export_pcs_bundle(
        AKTARecord(record),
        out,
        decision=d,
        scope_review_packet=scope_packet,
        scope_decision=scope_decision,
        scope_grant=scope_grant,
        pf_obligation=pf_obligation,
        validate=True,
    )
    return out


def test_pcs_v05_manifest_lists_all_artifacts(tmp_path: Path) -> None:
    out = _review_required_bundle(tmp_path)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    validate_against_schema(manifest, "pcs_akta_artifact.schema.json")
    assert manifest["schema_version"] == "akta-record-v0.5"
    expected = {
        "akta_record.json",
        "akta_decision.json",
        "policy_hash.txt",
        "domain_overlay_hash.txt",
        "tool_registry_hash.txt",
        "review_trigger.json",
        "scope_review_packet.json",
        "scope_decision.json",
        "scope_grant.json",
        "pf_obligation.json",
        "manifest.json",
    }
    assert set(manifest["files"]) == expected
    assert set(manifest["file_hashes"].keys()) == expected - {"manifest.json"}


def test_pcs_bundle_tamper_detection(tmp_path: Path) -> None:
    out = _review_required_bundle(tmp_path)
    validate_pcs_bundle(out)

    record_path = out / "akta_record.json"
    record_path.write_text(record_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="tamper"):
        validate_pcs_bundle(out)


def test_invalid_scope_grant_blocks_pcs_export(tmp_path: Path) -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Update active protocol."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_threshold",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
    )
    d = decision.to_dict()
    record = decision.to_record().to_dict()
    record["review_trigger"] = d["review_trigger"]
    bad_grant = {
        "grant_id": "SCOPE-GRANT-BAD",
        "granted_scope": "robot_queue_submission",
        "requested_scope": "active_protocol_update",
    }
    with pytest.raises(ValueError, match="Invalid SCOPE grant"):
        export_pcs_bundle(
            AKTARecord(record),
            tmp_path / "bad",
            decision=d,
            scope_grant=bad_grant,
            validate=True,
        )
