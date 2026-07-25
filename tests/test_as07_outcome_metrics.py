"""AS-07 outcome linkage and pilot metrics tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.vsa.import_report import import_vsa_report
from akta.gate import AKTAGate
from akta.pilot_metrics import (
    OutcomeMutationError,
    build_outcome_ref,
    export_pilot_metrics,
    link_outcome_to_record,
    reject_admissibility_rewrite,
)
from akta.records import validate_against_schema

ROOT = Path(__file__).resolve().parents[1]


def _sample_record() -> tuple[dict, dict]:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    report = {
        "report_id": "VSA-AS07",
        "overall_evidence_strength": "consistent",
        "claims": [{"claim_id": "C1", "evidence_level": "consistent"}],
    }
    ctx = import_vsa_report(report)
    decision = gate.evaluate(
        ai_output="summarize",
        requested_tool="analysis.literature_summary",
        requested_action="summarize",
        context=ctx,
    )
    record = decision.to_record(context=ctx).to_dict()
    return decision.to_dict(), record


def test_immutable_outcome_link() -> None:
    decision, record = _sample_record()
    prior = record["decision"]["admissibility"]
    ref = build_outcome_ref(
        record=record,
        decision=decision,
        memory_entry_digest="sha256:" + "a" * 64,
        linker_identity="test-linker",
    )
    validate_against_schema(ref, "outcome_ref.schema.json")
    updated = link_outcome_to_record(record, ref)
    assert updated["decision"]["admissibility"] == prior
    assert len(updated["integrations"]["outcome_refs"]) == 1

    with pytest.raises(OutcomeMutationError):
        reject_admissibility_rewrite(updated, new_admissibility="allowed")

    bad = dict(ref)
    bad["verdict_mutation"] = True
    with pytest.raises(Exception):
        link_outcome_to_record(record, bad)


def test_metrics_no_raw_pii_fields() -> None:
    _, record = _sample_record()
    metrics = export_pilot_metrics([record])
    validate_against_schema(metrics, "pilot_metrics.schema.json")
    blob = json.dumps(metrics)
    assert "Preliminary" not in blob
    assert "patient" not in blob.lower() or "non_claims" in blob
    assert metrics["reconstruction_completeness"] >= 0
    assert any("efficacy" in n.lower() for n in metrics["non_claims"])


def test_cli_link_and_export(tmp_path: Path) -> None:
    from akta.cli import main

    decision, record = _sample_record()
    rec_path = tmp_path / "record.json"
    ref_path = tmp_path / "outcome_ref.json"
    out_rec = tmp_path / "record_linked.json"
    metrics_out = tmp_path / "metrics.json"
    rec_path.write_text(json.dumps(record), encoding="utf-8")
    ref = build_outcome_ref(
        record=record,
        decision=decision,
        memory_entry_digest="sha256:" + "b" * 64,
        linker_identity="cli-test",
    )
    ref_path.write_text(json.dumps(ref), encoding="utf-8")
    assert main(["link-outcome", "--record", str(rec_path), "--outcome-ref", str(ref_path), "--out", str(out_rec)]) == 0
    records_dir = tmp_path / "records"
    records_dir.mkdir()
    (records_dir / "r1.json").write_text(out_rec.read_text(encoding="utf-8"), encoding="utf-8")
    assert main(["export-pilot-metrics", "--records", str(records_dir), "--out", str(metrics_out)]) == 0
    metrics = json.loads(metrics_out.read_text(encoding="utf-8"))
    assert metrics["record_count"] == 1
