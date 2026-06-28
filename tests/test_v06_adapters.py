"""Tests for v0.6 adapters: VSA, Scientific Memory, LabTrust-Gym, PF trace, PCS-Bench."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from adapters.labtrust_gym.import_scenario import convert_labtrust_scenario, import_labtrust_jsonl
from adapters.pcs.export_artifact import export_pcs_bundle
from adapters.pcs_bench.runner import AKTABenchScenario, run_suite
from adapters.pf_core.import_trace import import_pf_trace_certificate, merge_pf_trace_into_context
from adapters.scientific_memory.import_memory import import_from_pcs_bundle, import_from_record
from adapters.vsa.import_report import import_vsa_report, validate_vsa_report

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_vsa_rich_claim_graph() -> None:
    report = {
        "report_id": "VSA-RICH-001",
        "claims": [
            {"claim_id": "C1", "text": "Signal A", "evidence_level": "preliminary"},
            {"claim_id": "C2", "text": "Signal B", "evidence_level": "consistent"},
        ],
        "evidence_links": [
            {"link_id": "L1", "claim_id": "C1", "source_type": "run", "source_ref": "R1"},
        ],
        "validation_results": {"preliminary_experimental": True},
    }
    validate_vsa_report(report)
    ctx = import_vsa_report(report, validate=True)
    assert ctx["evidence_state"] == "E2_preliminary_signal"
    assert ctx["metadata"]["vsa_claim_graph"]["claim_count"] == 2


def test_pf_trace_import() -> None:
    obligation = {
        "obligation_id": "PF-OBL-TEST",
        "obligation_hash": "sha256:abc",
        "decision": "review_required",
        "enforcement_mode": "review_gate",
    }
    ctx = import_pf_trace_certificate(obligation)
    assert ctx["metadata"]["pf_trace_certificate_id"] == "PF-OBL-TEST"
    merged = merge_pf_trace_into_context({"domain": "test"}, obligation)
    assert merged["integrations"]["pf_trace_ref"] == "PF-OBL-TEST"


def test_scientific_memory_import(gate: AKTAGate, tmp_path: Path) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Analyze."},
        requested_tool="notebook.run_analysis",
        requested_action="analyze",
        context=AKTAContext.from_dict({"evidence_state": "E3_noisy_or_conflicting_evidence"}),
        deployment_profile="P2_analysis_assistant",
    )
    record = decision.to_record().to_dict()
    entry = import_from_record(record)
    assert entry["entry_type"] == "scientific_memory_import"
    assert entry.get("entry_hash")

    export_pcs_bundle(record, tmp_path, decision=decision.to_dict(), validate=True)
    bundle_entry = import_from_pcs_bundle(tmp_path)
    assert bundle_entry["source_record_id"] == record["record_id"]


def test_labtrust_gym_import(tmp_path: Path) -> None:
    ltg = {
        "scenario_id": "ltg_01",
        "prompt": "Search literature",
        "tool_calls": [{"tool": "literature_search.query", "action": "search"}],
    }
    akta = convert_labtrust_scenario(ltg)
    assert akta["requested_tool"] == "literature_search.query"
    assert akta["source"] == "labtrust_gym"

    jsonl = tmp_path / "ltg.jsonl"
    jsonl.write_text(json.dumps(ltg) + "\n", encoding="utf-8")
    scenarios = import_labtrust_jsonl(jsonl)
    assert len(scenarios) == 1


def test_pcs_bench_runner(gate: AKTAGate) -> None:
    scenario = AKTABenchScenario.from_jsonl_row({
        "scenario_id": "bench_01",
        "ai_output": {"summary": "Search."},
        "requested_tool": "literature_search.query",
        "requested_action": "search",
        "deployment_profile": "P1_literature_hypothesis_assistant",
        "context": {"evidence_state": "E0_no_evidence"},
    })
    result = run_suite([scenario], gate)
    assert result["total"] == 1
    assert result["results"][0]["admissibility"] == "allowed_with_logging"
