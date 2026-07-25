"""AS-06 SCOPE / PF / PCS binding chain tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.pcs.export_artifact import export_pcs_bundle, validate_pcs_bundle
from adapters.pf_core.export_obligation import build_pf_obligation, export_pf_obligation
from adapters.vsa.import_report import import_vsa_report
from akta.gate import AKTAGate
from akta.records import validate_against_schema

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "as06"


def _run_chain(tmp_path: Path) -> dict:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    report = json.loads((FIX / "vsa_report.json").read_text(encoding="utf-8"))
    ctx = import_vsa_report(report)
    decision = gate.evaluate(
        ai_output="propose protocol draft change",
        requested_tool="lab.protocol_draft",
        requested_action="draft",
        context=ctx,
        deployment_profile="P2_analysis_assistant",
    )
    data = decision.to_dict()
    record = decision.to_record(context=ctx).to_dict()
    (tmp_path / "decision.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (tmp_path / "record.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {"decision": data, "record": record, "ctx": ctx}


def test_scope_trigger_binding(tmp_path: Path) -> None:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    report = json.loads((FIX / "vsa_report.json").read_text(encoding="utf-8"))
    ctx = import_vsa_report(report)
    ctx.update(
        {
            "evidence_state": "E5_internally_replicated_evidence",
            "validation_status": "V4_internally_replicated",
        }
    )
    decision = gate.evaluate(
        ai_output={"summary": "Recommend next experiment based on replicated evidence."},
        requested_tool="experiment_planner.create_run_plan",
        requested_action="create_run_plan",
        context=ctx,
        deployment_profile="P3_review_gated_evidence_interpreter",
        domain_overlay="computational_science_v0",
    )
    data = decision.to_dict()
    trigger = data.get("review_trigger")
    assert trigger is not None, data.get("admissibility")
    assert trigger["decision_id"] == data["decision_id"]
    assert trigger.get("bindings", {}).get("decision_id") == data["decision_id"]
    assert trigger["policy_hash"] == data["bindings"]["policy_hash"]
    # Persist chain fixture artifacts for offline inspection.
    (tmp_path / "decision.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    record = decision.to_record(context=ctx).to_dict()
    (tmp_path / "record.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    validate_against_schema(trigger, "review_trigger.schema.json")


def test_pf_obligation_binding(tmp_path: Path) -> None:
    chain = _run_chain(tmp_path)
    record = chain["record"]
    obl = build_pf_obligation(record, decision_id=chain["decision"]["decision_id"])
    assert obl["bindings"]["decision_id"] == chain["decision"]["decision_id"]
    assert obl["bindings"]["record_id"] == record["record_id"]
    assert obl["policy_hash"] == record["bindings"]["policy_hash"]
    path = export_pf_obligation(record, tmp_path, decision_id=chain["decision"]["decision_id"])
    assert path.is_file()


def test_pf_tamper_negative(tmp_path: Path) -> None:
    chain = _run_chain(tmp_path)
    record = dict(chain["record"])
    bindings = dict(record["bindings"])
    bindings["policy_hash"] = "sha256:" + "0" * 64
    record["bindings"] = bindings
    with pytest.raises(ValueError, match="digest mismatch"):
        build_pf_obligation(record, decision_id=chain["decision"]["decision_id"])


def test_pcs_release_validation(tmp_path: Path) -> None:
    chain = _run_chain(tmp_path)
    out = tmp_path / "pcs"
    export_pcs_bundle(
        chain["record"],
        out,
        decision=chain["decision"],
        validate=True,
    )
    validate_pcs_bundle(out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.get("decision_id") == chain["decision"]["decision_id"]
    assert manifest.get("record_id") == chain["record"]["record_id"]
    assert (manifest.get("bindings") or {}).get("policy_hash") == chain["record"]["bindings"][
        "policy_hash"
    ]


def test_pcs_tamper_negative(tmp_path: Path) -> None:
    chain = _run_chain(tmp_path)
    out = tmp_path / "pcs"
    export_pcs_bundle(chain["record"], out, decision=chain["decision"], validate=True)
    # Tamper record file after export.
    rec_path = out / "akta_record.json"
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    rec["decision"]["decision_reason"] = "tampered"
    rec_path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="tamper"):
        validate_pcs_bundle(out)
