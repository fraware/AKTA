"""Comprehensive PCS v0.5 full-chain tamper validation (contract tests)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.pcs.export_artifact import export_pcs_bundle, validate_pcs_bundle
from akta import AKTAGate, AKTAContext
from akta.records import AKTARecord

ROOT = Path(__file__).resolve().parent.parent.parent


def _full_chain_bundle(tmp_path: Path) -> Path:
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

    out = tmp_path / "pcs"
    export_pcs_bundle(
        AKTARecord(record),
        out,
        decision=d,
        scope_review_packet={"packet_type": "scope_review_packet"},
        scope_decision={"status": "granted", "granted_scope": "protocol_draft"},
        scope_grant={
            "grant_id": "SCOPE-GRANT-TAMPER",
            "granted_scope": "protocol_draft",
            "requested_scope": "active_protocol_update",
        },
        pf_obligation={"obligation_type": "tool_review", "obligation_id": "PF-OBL-TAMPER"},
        validate=True,
    )
    return out


def test_pcs_full_chain_fixture_validates() -> None:
    bundle = ROOT / "examples" / "integrated_protocol_drift" / "pcs_bundle"
    validate_pcs_bundle(bundle)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "akta-record-v0.5"
    assert len(manifest["file_hashes"]) == 10


@pytest.mark.parametrize(
    "artifact",
    [
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
    ],
)
def test_pcs_tamper_each_artifact_detected(tmp_path: Path, artifact: str) -> None:
    out = _full_chain_bundle(tmp_path)
    path = out / artifact
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="tamper"):
        validate_pcs_bundle(out)


def test_pcs_tamper_missing_listed_artifact(tmp_path: Path) -> None:
    out = _full_chain_bundle(tmp_path)
    (out / "scope_grant.json").unlink()
    with pytest.raises(ValueError, match="missing listed artifact"):
        validate_pcs_bundle(out)


def test_pcs_tamper_manifest_hash_mismatch(tmp_path: Path) -> None:
    out = _full_chain_bundle(tmp_path)
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["manifest_hash"] = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest_hash"):
        validate_pcs_bundle(out)


def test_pcs_tamper_files_list_mismatch(tmp_path: Path) -> None:
    out = _full_chain_bundle(tmp_path)
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = sorted(manifest["files"] + ["extra.json"])
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="files list"):
        validate_pcs_bundle(out)


def test_pcs_validate_requires_file_hashes(tmp_path: Path) -> None:
    out = _full_chain_bundle(tmp_path)
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["file_hashes"]
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="file_hashes"):
        validate_pcs_bundle(out)
