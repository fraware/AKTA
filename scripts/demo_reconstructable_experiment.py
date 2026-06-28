"""Reconstructable experiment demo — full AKTA v0.6 integration chain."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

DEMO_TIMESTAMP = "2026-06-28T14:00:00Z"
DEMO_DECISION_ID = "AKTA-DEC-RECON0001"
DEMO_RECORD_ID = "AKTA-SAR-RECON0001"


def _rehash_record(record: dict[str, Any]) -> dict[str, Any]:
    from akta.hash import hash_object

    record = dict(record)
    record["record_hash"] = hash_object(
        {k: v for k, v in record.items() if k != "record_hash"}
    )
    return record


def stabilize_decision(decision: dict[str, Any], *, decision_id: str, record_id: str) -> dict[str, Any]:
    from akta.hash import hash_object

    d = dict(decision)
    d["decision_id"] = decision_id
    d["timestamp"] = DEMO_TIMESTAMP
    if d.get("review_trigger"):
        rt = dict(d["review_trigger"])
        rt["decision_id"] = decision_id
        rt["akta_decision_id"] = decision_id
        rt["source_record_id"] = record_id
        rt["akta_record_id"] = record_id
        rt["review_trigger_hash"] = hash_object(
            {k: v for k, v in rt.items() if k != "review_trigger_hash"}
        )
        d["review_trigger"] = rt
    return d


def run_demo() -> int:
    from akta import AKTAGate, AKTAContext
    from akta.records import AKTARecord, AKTADecision
    from akta.review_packet import export_human_review_packet
    from adapters.labtrust_gym.import_scenario import convert_labtrust_scenario
    from adapters.pcs.export_artifact import export_pcs_bundle, validate_pcs_bundle
    from adapters.pcs_bench.runner import AKTABenchScenario, run_suite
    from adapters.pf_core.export_obligation import build_pf_obligation
    from adapters.pf_core.import_trace import merge_pf_trace_into_context
    from adapters.scope.client import detect_adapter_mode, submit_review_trigger
    from adapters.scientific_memory.import_memory import export_memory_entry, import_from_pcs_bundle
    from adapters.vsa.import_report import import_vsa_report, validate_vsa_report
    from evals.run_scenarios import run_scenario_eval

    demo_dir = ROOT / "examples" / "reconstructable_experiment"
    demo_dir.mkdir(parents=True, exist_ok=True)
    pcs_dir = demo_dir / "pcs_bundle"

    adapter_mode = detect_adapter_mode()
    print("=== AKTA v0.6 Demo: Reconstructable Experiment Chain ===")
    print(f"SCOPE adapter: {adapter_mode}\n")

    vsa_report = json.loads((ROOT / "examples" / "integrated_weak_evidence" / "vsa_report.json").read_text(encoding="utf-8"))
    vsa_report["claims"] = vsa_report.get("claims") or [
        {
            "claim_id": "C1",
            "text": "Preliminary signal favors condition B.",
            "evidence_level": "preliminary",
            "confidence": 0.55,
        }
    ]
    vsa_report["evidence_links"] = [
        {"link_id": "L1", "claim_id": "C1", "source_type": "experiment", "source_ref": "RUN-001", "weight": 0.6}
    ]
    validate_vsa_report(vsa_report)
    (demo_dir / "vsa_report.json").write_text(json.dumps(vsa_report, indent=2), encoding="utf-8")

    vsa_ctx = import_vsa_report(vsa_report, validate=True)
    context_data = {"evidence_state": "E2_preliminary_signal", "domain": "materials"}
    context_data.update({k: v for k, v in vsa_ctx.items() if k != "metadata"})
    context_data.setdefault("metadata", {}).update(vsa_ctx.get("metadata", {}))

    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    ai_output = {"summary": "Prioritize condition B based on preliminary VSA signal."}

    decision = gate.evaluate(
        ai_output=ai_output,
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_next_run",
        context=AKTAContext.from_dict(context_data),
        deployment_profile="P2_analysis_assistant",
        domain_overlay="generic_lab_v0",
    )
    d = stabilize_decision(decision.to_dict(), decision_id=DEMO_DECISION_ID, record_id=DEMO_RECORD_ID)
    AKTADecision(d).save(demo_dir / "akta_decision.json")

    record = decision.to_record(ai_output=ai_output, context=context_data)
    record_data = _rehash_record(record.to_dict())
    record_data["record_id"] = DEMO_RECORD_ID
    record_data["timestamp"] = DEMO_TIMESTAMP
    AKTARecord(record_data).save(demo_dir / "akta_record.json")

    pf_obligation = build_pf_obligation(record_data, decision_id=d["decision_id"])
    (demo_dir / "pf_obligation.json").write_text(json.dumps(pf_obligation, indent=2), encoding="utf-8")

    context_with_trace = merge_pf_trace_into_context(context_data, pf_obligation)

    scope_packet = None
    scope_grant = None
    scope_decision = None
    if d.get("review_trigger"):
        review_packet = export_human_review_packet(d["review_trigger"], record=record_data, decision=d)
        (demo_dir / "human_review_packet.json").write_text(json.dumps(review_packet, indent=2), encoding="utf-8")

        scope_result = submit_review_trigger(
            d["review_trigger"],
            record=record_data,
            grant_scope="single_run_queue_priority",
            reviewer_id="lab_operations_lead",
        )
        if not scope_result.error:
            scope_packet = scope_result.review_packet
            scope_grant = scope_result.grant
            scope_decision = scope_result.decision
            for name, payload in (
                ("scope_review_packet.json", scope_packet),
                ("scope_grant.json", scope_grant),
                ("scope_decision.json", scope_decision),
            ):
                if payload:
                    (demo_dir / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")

            regate = gate.evaluate_with_grant(
                ai_output=ai_output,
                requested_tool="lab_scheduler.prioritize",
                requested_action="prioritize_next_run",
                context=AKTAContext.from_dict(context_with_trace),
                deployment_profile="P2_analysis_assistant",
                domain_overlay="generic_lab_v0",
                scope_grant=scope_grant,
                record=record_data,
                trigger=d["review_trigger"],
            )
            (demo_dir / "akta_decision_after_grant.json").write_text(
                json.dumps(regate.to_dict(), indent=2), encoding="utf-8"
            )

    export_pcs_bundle(
        AKTARecord(record_data),
        pcs_dir,
        decision=d,
        scope_review_packet=scope_packet,
        scope_decision=scope_decision,
        scope_grant=scope_grant,
        pf_obligation=pf_obligation,
        vsa_report=vsa_report,
        validate=True,
    )
    validate_pcs_bundle(pcs_dir)

    memory_entry = import_from_pcs_bundle(pcs_dir)
    export_memory_entry(memory_entry, demo_dir / "scientific_memory_entry.json")

    ltg_scenario = convert_labtrust_scenario({
        "scenario_id": "recon_demo_01",
        "prompt": "Prioritize run queue after weak evidence review.",
        "tool_calls": [{
            "tool": "lab_scheduler.prioritize",
            "action": "prioritize_next_run",
            "deployment_profile": "P2_analysis_assistant",
        }],
    })
    bench = AKTABenchScenario.from_jsonl_row({
        **ltg_scenario,
        "deployment_profile": "P2_analysis_assistant",
    })
    bench_result = run_suite([bench], gate)
    (demo_dir / "pcs_bench_result.json").write_text(json.dumps(bench_result, indent=2), encoding="utf-8")

    canonical = run_scenario_eval(
        ROOT / "scenarios" / "canonical_5.jsonl",
        ROOT / "scenarios" / "expected_decisions.jsonl",
        ROOT / "policy",
        ROOT / "overlays",
    )

    print(f"Decision:       {d['admissibility']}")
    print(f"VSA claims:     {len(vsa_report.get('claims', []))}")
    print(f"PCS bundle:     {pcs_dir / 'manifest.json'}")
    print(f"Memory entry:   {demo_dir / 'scientific_memory_entry.json'}")
    print(f"PCS-Bench:      {bench_result['passed_count']}/{bench_result['total']} passed")
    print(f"Canonical eval: {canonical['accuracy']:.0%}")
    print(f"\nArtifacts in {demo_dir}")
    return 0 if canonical["passed"] and bench_result["passed"] else 1


if __name__ == "__main__":
    sys.exit(run_demo())
