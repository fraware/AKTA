"""Tests for AKTA adapters."""

import json
from pathlib import Path

from akta import AKTAGate, AKTAContext
from adapters.vsa.import_report import import_vsa_report
from adapters.pf_core.export_obligation import build_pf_obligation, export_pf_obligation
from adapters.pcs.export_artifact import export_pcs_bundle

ROOT = Path(__file__).resolve().parent.parent


def test_vsa_import_maps_evidence() -> None:
    report = json.loads((ROOT / "examples" / "weak_evidence" / "vsa_report.json").read_text())
    ctx = import_vsa_report(report)
    assert ctx["evidence_state"] == "E2_preliminary_signal"
    assert ctx["validation_status"] == "V0_unvalidated"


def test_pf_export(tmp_path: Path) -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize B."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_next_run",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P2_analysis_assistant",
        domain_overlay="generic_lab_v0",
    )
    record = decision.to_record()
    path = export_pf_obligation(record, tmp_path)
    obligation = json.loads(path.read_text())
    assert obligation["source"] == "AKTA"
    assert obligation["decision"] == "blocked"
    assert "lab_scheduler.prioritize" in obligation["blocked_tools"]


def test_pcs_export(tmp_path: Path) -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize B."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_next_run",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P2_analysis_assistant",
        domain_overlay="generic_lab_v0",
    )
    record = decision.to_record()
    out = export_pcs_bundle(record, tmp_path / "pcs")
    assert (out / "manifest.json").exists()
    assert (out / "akta_record.json").exists()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["artifact_type"] == "akta_scientific_action_record"
