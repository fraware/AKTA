"""Integrated weak-evidence demo — AKTA v0.2 artifact pipeline (no SCOPE chain).

For the canonical AKTA x SCOPE integration demo, use
`scripts/demo_akta_scope_protocol_drift.py` instead.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# Fixed identifiers for deterministic example artifacts (hashes derive from content).
DEMO_TIMESTAMP = "2026-06-01T12:00:00Z"
DEMO_DECISION_ID = "AKTA-DEC-DEMO0001"
DEMO_RECORD_ID = "AKTA-SAR-DEMO0001"
DEMO_REVIEW_DECISION_ID = "AKTA-DEC-DEMO0002"
DEMO_REVIEW_RECORD_ID = "AKTA-SAR-DEMO0002"
DEMO_REVIEW_TRIGGER_ID = "AKTA-REVTRIG-DEMO0001"


def _rehash_review_trigger(trigger: dict[str, Any]) -> dict[str, Any]:
    from akta.hash import hash_object

    trigger = dict(trigger)
    trigger["review_trigger_hash"] = hash_object(
        {k: v for k, v in trigger.items() if k != "review_trigger_hash"}
    )
    return trigger


def _rehash_record(record: dict[str, Any]) -> dict[str, Any]:
    from akta.hash import hash_object

    record = dict(record)
    record["record_hash"] = hash_object(
        {k: v for k, v in record.items() if k != "record_hash"}
    )
    return record


def stabilize_decision(
    decision: dict[str, Any],
    *,
    decision_id: str,
    record_id: str,
    timestamp: str = DEMO_TIMESTAMP,
    review_trigger_id: str | None = None,
) -> dict[str, Any]:
    """Apply fixed demo identifiers and recompute content hashes."""
    d = dict(decision)
    d["decision_id"] = decision_id
    d["timestamp"] = timestamp
    if d.get("review_trigger"):
        rt = dict(d["review_trigger"])
        rt["decision_id"] = decision_id
        rt["akta_decision_id"] = decision_id
        rt["source_record_id"] = record_id
        rt["akta_record_id"] = record_id
        if review_trigger_id:
            rt["review_trigger_id"] = review_trigger_id
        d["review_trigger"] = _rehash_review_trigger(rt)
    return d


def stabilize_record(
    record: dict[str, Any],
    *,
    record_id: str,
    timestamp: str = DEMO_TIMESTAMP,
) -> dict[str, Any]:
    record = dict(record)
    record["record_id"] = record_id
    record["timestamp"] = timestamp
    return _rehash_record(record)


def run_demo() -> int:
    from akta import AKTAGate, AKTAContext
    from akta.records import AKTARecord, AKTADecision
    from adapters.pcs.export_artifact import export_pcs_bundle
    from adapters.pf_core.export_obligation import export_pf_obligation
    from adapters.vsa.import_report import import_vsa_report
    from evals.run_scenarios import run_scenario_eval

    demo_dir = ROOT / "examples" / "integrated_weak_evidence"
    demo_dir.mkdir(parents=True, exist_ok=True)
    pcs_dir = demo_dir / "pcs_bundle"
    legacy_pcs = demo_dir / "pcs_artifacts"
    if legacy_pcs.exists():
        shutil.rmtree(legacy_pcs)

    print("=== AKTA Demo: Integrated Weak-Evidence Pipeline (AKTA/PF/PCS) ===\n")

    vsa_report = json.loads((demo_dir / "vsa_report.json").read_text(encoding="utf-8"))
    vsa_ctx = import_vsa_report(vsa_report)
    context_data = json.loads((demo_dir / "context.json").read_text(encoding="utf-8"))
    context_data.update({k: v for k, v in vsa_ctx.items() if k != "metadata"})
    context_data.setdefault("metadata", {}).update(vsa_ctx.get("metadata", {}))

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
    d = stabilize_decision(
        decision.to_dict(),
        decision_id=DEMO_DECISION_ID,
        record_id=DEMO_RECORD_ID,
    )
    decision_path = demo_dir / "akta_decision.json"
    AKTADecision(d).save(decision_path)

    record = decision.to_record(ai_output=ai_output, context=context_data)
    record_data = stabilize_record(record.to_dict(), record_id=DEMO_RECORD_ID)
    record_path = demo_dir / "akta_record.json"
    AKTARecord(record_data).save(record_path)

    pf_path = export_pf_obligation(
        AKTARecord(record_data), demo_dir, validate=True, decision_id=d["decision_id"]
    )
    pf_obligation = json.loads(pf_path.read_text(encoding="utf-8"))
    (demo_dir / "pf_obligation.json").write_text(json.dumps(pf_obligation, indent=2), encoding="utf-8")

    # Review trigger is exported only when the primary weak-evidence gate path requires review.
    review_trigger_path = demo_dir / "review_trigger.json"
    if d.get("review_trigger"):
        (review_trigger_path).write_text(json.dumps(d["review_trigger"], indent=2), encoding="utf-8")
    elif review_trigger_path.exists():
        review_trigger_path.unlink()

    export_pcs_bundle(
        AKTARecord(record_data), pcs_dir, decision=d, validate=True
    )

    # Remove non-deterministic per-record PF export filename; keep canonical pf_obligation.json
    if pf_path.name != "pf_obligation.json":
        pf_path.unlink(missing_ok=True)
    for stale in demo_dir.glob("pf_obligation_AKTA-SAR-*.json"):
        stale.unlink(missing_ok=True)

    print(f"Decision:     {d['admissibility']} ({d['scientific_action_type']})")
    print(f"Record:       {record_data['record_id']}")
    print(f"PF obligation: {pf_obligation['obligation_type']}")
    print(f"PCS bundle:   {pcs_dir / 'manifest.json'}")
    print(f"Review trigger: {review_trigger_path if review_trigger_path.exists() else '(none — primary path is blocked, not review_required)'}")
    print(f"Consequentiality: {d.get('consequentiality')} — {d.get('consequentiality_reason', '')[:60]}")

    reports_dir = ROOT / "evals" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    canonical = run_scenario_eval(
        ROOT / "scenarios" / "canonical_5.jsonl",
        ROOT / "scenarios" / "expected_decisions.jsonl",
        ROOT / "policy",
        ROOT / "overlays",
    )
    public = run_scenario_eval(
        ROOT / "scenarios" / "public_100.jsonl",
        ROOT / "scenarios" / "expected_decisions.jsonl",
        ROOT / "policy",
        ROOT / "overlays",
    )
    benchmark = {
        "demo": "integrated_weak_evidence_v0.3",
        "canonical_5": {"accuracy": canonical["accuracy"], "passed": canonical["passed"]},
        "public_100": {"accuracy": public["accuracy"], "passed": public["passed"]},
        "metrics": public.get("metrics", {}),
    }
    report_path = reports_dir / "demo_integrated_weak_evidence.json"
    report_path.write_text(json.dumps(benchmark, indent=2), encoding="utf-8")
    print(f"\nBenchmark: canonical={canonical['accuracy']:.0%}, public_100={public['accuracy']:.0%}")
    print(f"Artifacts in {demo_dir}")
    return 0 if canonical["passed"] and public["passed"] else 1


if __name__ == "__main__":
    sys.exit(run_demo())
