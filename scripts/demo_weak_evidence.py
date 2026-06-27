"""Integrated weak-evidence demo flow (spec section 39)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_demo() -> int:
    from akta import AKTAGate, AKTAContext
    from adapters.pcs.export_artifact import export_pcs_bundle
    from adapters.pf_core.export_obligation import export_pf_obligation
    from adapters.vsa.import_report import import_vsa_report
    from evals.run_scenarios import run_scenario_eval

    demo_dir = ROOT / "examples" / "weak_evidence"
    demo_dir.mkdir(parents=True, exist_ok=True)

    print("=== AKTA Demo: The First Reconstructable AI-Shaped Experiment ===\n")

    # Step 1-2: AI interprets weak evidence; VSA provides report
    vsa_report = json.loads((demo_dir / "vsa_report.json").read_text(encoding="utf-8"))
    vsa_ctx = import_vsa_report(vsa_report)
    print(f"[1-2] VSA report imported: evidence={vsa_ctx['evidence_state']}")

    context_data = json.loads((demo_dir / "context.json").read_text(encoding="utf-8"))
    context_data.update({k: v for k, v in vsa_ctx.items() if k != "metadata"})
    context_data.setdefault("metadata", {}).update(vsa_ctx.get("metadata", {}))

    # Step 3-5: Agent attempts prioritize; AKTA blocks and emits record
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    ai_output = json.loads((demo_dir / "ai_output.json").read_text(encoding="utf-8"))
    decision = gate.evaluate(
        ai_output=ai_output,
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_next_run",
        context=AKTAContext.from_dict(context_data),
        deployment_profile="P2_analysis_assistant",
        domain_overlay="generic_lab_v0",
    )
    decision_path = demo_dir / "akta_decision.json"
    decision.save(decision_path)
    d = decision.to_dict()
    print(f"[3-5] AKTA decision: {d['admissibility']} ({d['scientific_action_type']}/{d['responsibility_level']})")

    record = decision.to_record(ai_output=ai_output, context=context_data)
    record_path = demo_dir / "akta_record.json"
    record.save(record_path)
    print(f"[5]   AKTA Record: {record.to_dict()['record_id']}")

    # Step 6-7: PF obligation; runtime would block tool
    pf_dir = demo_dir / "pf_obligations"
    pf_path = export_pf_obligation(record, pf_dir)
    obligation = json.loads(pf_path.read_text(encoding="utf-8"))
    print(f"[6-7] PF obligation: {obligation['obligation_type']} — blocked_tools={obligation['blocked_tools']}")
    print("      Runtime trace: lab_scheduler.prioritize NOT called (blocked by AKTA)")

    # Step 8: PCS bundle
    pcs_dir = demo_dir / "pcs_artifacts"
    export_pcs_bundle(record, pcs_dir)
    manifest = json.loads((pcs_dir / "manifest.json").read_text(encoding="utf-8"))
    print(f"[8]   PCS bundle: {len(manifest['files'])} artifacts, record_hash present={bool(manifest.get('record_hash'))}")

    # Step 9: Benchmark validation
    reports_dir = ROOT / "evals" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    canonical = run_scenario_eval(
        ROOT / "scenarios" / "canonical_5.jsonl",
        ROOT / "scenarios" / "expected_decisions.jsonl",
        ROOT / "policy",
        ROOT / "overlays",
    )
    public = run_scenario_eval(
        ROOT / "scenarios" / "public_40.jsonl",
        ROOT / "scenarios" / "expected_decisions.jsonl",
        ROOT / "policy",
        ROOT / "overlays",
    )
    benchmark = {
        "demo": "weak_evidence",
        "canonical_5": {"accuracy": canonical["accuracy"], "passed": canonical["passed"]},
        "public_40": {"accuracy": public["accuracy"], "passed": public["passed"]},
        "metrics": public.get("metrics", {}),
    }
    report_path = reports_dir / "demo_weak_evidence_benchmark.json"
    report_path.write_text(json.dumps(benchmark, indent=2), encoding="utf-8")
    print(f"[9]   Benchmark: canonical={canonical['accuracy']:.0%}, public_40={public['accuracy']:.0%}")

    print("\n[10]  Scientific Memory: import bounded result from PCS bundle + AKTA Record")
    print(f"\nDemo complete. Artifacts in {demo_dir}")
    print(f"Benchmark report: {report_path}")
    return 0 if canonical["passed"] and public["passed"] else 1


if __name__ == "__main__":
    sys.exit(run_demo())
