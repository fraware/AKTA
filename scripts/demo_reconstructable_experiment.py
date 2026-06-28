"""Reconstructable experiment demo — canonical AKTA v0.7 integration chain."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "dist" / "reconstructable_experiment"

DEMO_TIMESTAMP = "2026-06-28T14:00:00Z"
DEMO_DECISION_ID = "AKTA-DEC-RECON0001"
DEMO_RECORD_ID = "AKTA-SAR-RECON0001"
DEMO_REVIEW_TRIGGER_ID = "AKTA-REVTRIG-RECON0001"


def _rehash_record(record: dict[str, Any]) -> dict[str, Any]:
    from akta.hash import hash_object

    record = dict(record)
    record["record_hash"] = hash_object(
        {k: v for k, v in record.items() if k != "record_hash"}
    )
    return record


def _rehash_trigger(trigger: dict[str, Any]) -> dict[str, Any]:
    from akta.hash import hash_object

    trigger = dict(trigger)
    trigger["review_trigger_hash"] = hash_object(
        {k: v for k, v in trigger.items() if k != "review_trigger_hash"}
    )
    return trigger


def stabilize_decision(
    decision: dict[str, Any],
    *,
    decision_id: str,
    record_id: str,
    review_trigger_id: str | None = None,
) -> dict[str, Any]:
    d = dict(decision)
    d["decision_id"] = decision_id
    d["timestamp"] = DEMO_TIMESTAMP
    if d.get("review_trigger"):
        rt = dict(d["review_trigger"])
        rt["decision_id"] = decision_id
        rt["akta_decision_id"] = decision_id
        rt["source_record_id"] = record_id
        rt["akta_record_id"] = record_id
        if review_trigger_id:
            rt["review_trigger_id"] = review_trigger_id
        d["review_trigger"] = _rehash_trigger(rt)
    return d


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _linkage_report(artifacts: dict[str, Path]) -> dict[str, Any]:
    links: list[dict[str, str]] = []
    decision = json.loads(artifacts["01_akta_decision.json"].read_text(encoding="utf-8"))
    record = json.loads(artifacts["02_akta_record.json"].read_text(encoding="utf-8"))
    trigger = json.loads(artifacts["03_review_trigger.json"].read_text(encoding="utf-8"))
    grant = json.loads(artifacts["06_scope_grant.json"].read_text(encoding="utf-8"))
    manifest = json.loads((artifacts["09_pcs_bundle"] / "manifest.json").read_text(encoding="utf-8"))

    links.append({
        "from": "01_akta_decision.json",
        "to": "02_akta_record.json",
        "field": "decision_id/record_id",
        "ok": decision["decision_id"].replace("DEC", "SAR") in record["record_id"],
    })
    links.append({
        "from": "03_review_trigger.json",
        "to": "01_akta_decision.json",
        "field": "akta_decision_id",
        "ok": trigger.get("akta_decision_id") == decision["decision_id"],
    })
    links.append({
        "from": "06_scope_grant.json",
        "to": "03_review_trigger.json",
        "field": "requested_scope",
        "ok": (
            (grant.get("source") or {}).get("requested_scope")
            or grant.get("requested_scope")
        ) == trigger.get("requested_scope"),
    })
    links.append({
        "from": "09_pcs_bundle/manifest.json",
        "to": "02_akta_record.json",
        "field": "record_hash",
        "ok": manifest.get("record_hash") == record.get("record_hash"),
    })
    return {"linkage": links, "all_linked": all(l["ok"] for l in links)}


def run_demo() -> int:
    from akta import AKTAGate, AKTAContext
    from akta.records import AKTARecord, AKTADecision
    from adapters.labtrust_gym.import_scenario import convert_labtrust_scenario
    from adapters.pcs.export_artifact import export_pcs_bundle, validate_pcs_bundle
    from adapters.pcs_bench.runner import AKTABenchScenario, run_suite
    from adapters.pf_core.export_obligation import build_pf_obligation
    from adapters.pf_core.import_trace import merge_pf_trace_into_context
    from adapters.scope.client import detect_adapter_mode, submit_review_trigger
    from adapters.scientific_memory.import_memory import export_memory_entry, import_from_pcs_bundle
    from adapters.vsa.import_report import import_vsa_report, validate_vsa_report

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pcs_dir = OUT_DIR / "09_pcs_bundle"

    adapter_mode = detect_adapter_mode()
    print("=== AKTA v0.7 Demo: Reconstructable Experiment Chain ===")
    print(f"SCOPE adapter: {adapter_mode}\n")

    vsa_report = json.loads(
        (ROOT / "examples" / "integrated_weak_evidence" / "vsa_report.json").read_text(encoding="utf-8")
    )
    vsa_report["claims"] = vsa_report.get("claims") or [
        {
            "claim_id": "C1",
            "text": "Preliminary signal favors condition B.",
            "evidence_level": "preliminary",
            "confidence": 0.55,
        }
    ]
    vsa_report["evidence_links"] = [
        {
            "link_id": "L1",
            "claim_id": "C1",
            "source_type": "experiment",
            "source_ref": "RUN-001",
            "weight": 0.6,
        }
    ]
    validate_vsa_report(vsa_report)
    _write_json(OUT_DIR / "00_vsa_report.json", vsa_report)

    context_data = {
        "evidence_state": "E2_preliminary_signal",
        "domain": "generic",
        "protocol_version": "PROTO-RECON-V1",
        "validation_status": "V3_preliminary_experimental_support",
    }
    vsa_ctx = import_vsa_report(vsa_report, validate=True)
    if vsa_ctx.get("evidence_state"):
        context_data["evidence_state"] = vsa_ctx["evidence_state"]
    context_data.update({
        k: v for k, v in vsa_ctx.items() if k not in ("metadata", "evidence_state")
    })
    vsa_metadata = dict(vsa_ctx.get("metadata", {}))
    if vsa_ctx.get("evidence_state"):
        vsa_metadata["vsa_derived_evidence_state"] = vsa_ctx["evidence_state"]
    context_data.setdefault("metadata", {}).update(vsa_metadata)

    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    ai_output = {"summary": "Prioritize condition B based on preliminary VSA signal."}

    # Case A: weak evidence + P2 + queue priority must not pass silently.
    case_a = gate.evaluate(
        ai_output=ai_output,
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_next_run",
        context=AKTAContext.from_dict(context_data),
        deployment_profile="P2_analysis_assistant",
        domain_overlay="generic_lab_v0",
    )
    case_a_dict = stabilize_decision(
        case_a.to_dict(),
        decision_id=DEMO_DECISION_ID,
        record_id=DEMO_RECORD_ID,
        review_trigger_id=DEMO_REVIEW_TRIGGER_ID,
    )
    assert case_a_dict["admissibility"] in ("blocked", "review_required"), (
        f"Case A expected blocked/review_required, got {case_a_dict['admissibility']}"
    )
    print(f"Case A (pre-grant): {case_a_dict['admissibility']}")

    from akta.overlays import DomainOverlay
    from akta.records import build_review_trigger

    overlay_obj = DomainOverlay.load("generic_lab_v0", ROOT / "overlays")
    trigger = build_review_trigger(
        decision_id=case_a_dict["decision_id"],
        record_id=case_a_dict["decision_id"].replace("DEC", "SAR"),
        role=case_a_dict.get("required_review_role") or "lab_manager",
        action_type=case_a_dict["scientific_action_type"],
        requested_tool=case_a_dict["requested_tool"],
        requested_action=case_a_dict["requested_action"],
        deployment_profile=case_a_dict["deployment_profile"],
        scientific_action_type=case_a_dict["scientific_action_type"],
        responsibility_level=case_a_dict["responsibility_level"],
        evidence_state=case_a_dict["evidence_state"],
        validation_status=case_a_dict["validation_status"],
        verification_status=case_a_dict["verification_status"],
        admissibility=case_a_dict["admissibility"],
        decision_reason=case_a_dict["decision_reason"],
        blocked_tools=case_a_dict.get("blocked_tools"),
        allowed_next_steps=case_a_dict.get("next_admissible_steps"),
        policy_hash=case_a_dict.get("policy_hash", ""),
        tool_registry_hash=case_a_dict.get("tool_registry_hash", ""),
        domain_overlay_hash=case_a_dict.get("domain_overlay_hash"),
        classifier_confidence=case_a_dict.get("classifier_confidence", 0.95),
        classification_rationale=case_a_dict.get("classification_rationale", ""),
        consequentiality=case_a_dict.get("consequentiality", False),
        consequentiality_reason=case_a_dict.get("consequentiality_reason", ""),
        scientific_context={
            "domain": case_a_dict.get("domain", "generic"),
            "protocol_version": context_data.get("protocol_version"),
        },
        scope_config=gate.policy.tool_to_requested_scope,
        overlay=overlay_obj,
    )
    trigger = _rehash_trigger({
        **trigger,
        "review_trigger_id": DEMO_REVIEW_TRIGGER_ID,
        "decision_id": DEMO_DECISION_ID,
        "akta_decision_id": DEMO_DECISION_ID,
        "source_record_id": DEMO_RECORD_ID,
        "akta_record_id": DEMO_RECORD_ID,
        "requested_scope": "single_run_queue_priority",
    })
    case_a_dict["review_trigger"] = trigger
    d = case_a_dict
    _write_json(OUT_DIR / "01_akta_decision.json", d)

    record = case_a.to_record(ai_output=ai_output, context=context_data)
    record_data = _rehash_record(record.to_dict())
    record_data["record_id"] = DEMO_RECORD_ID
    record_data["timestamp"] = DEMO_TIMESTAMP
    record_data["review_trigger"] = trigger
    _write_json(OUT_DIR / "02_akta_record.json", record_data)

    _write_json(OUT_DIR / "03_review_trigger.json", trigger)

    # Case B: SCOPE grants single_run_queue_priority (does not override AKTA policy).
    scope_result = submit_review_trigger(
        trigger,
        record=record_data,
        grant_scope="single_run_queue_priority",
        reviewer_id="lab_manager",
    )
    if scope_result.error:
        print(f"SCOPE adapter error: {scope_result.error}")
        return 1
    scope_packet = scope_result.review_packet or {}
    scope_grant = scope_result.grant or {}
    scope_decision = scope_result.decision or {}
    approved_scope = (
        (scope_grant.get("authorization") or {}).get("approved_scope")
        or scope_grant.get("granted_scope")
    )
    assert approved_scope == "single_run_queue_priority", (
        f"Case B expected single_run_queue_priority grant, got {approved_scope}"
    )
    print(f"Case B (SCOPE grant): {approved_scope}")
    _write_json(OUT_DIR / "04_scope_packet.json", scope_packet)
    _write_json(OUT_DIR / "05_scope_decision.json", scope_decision)
    _write_json(OUT_DIR / "06_scope_grant.json", scope_grant)

    pf_obligation = build_pf_obligation(record_data, decision_id=d["decision_id"])
    _write_json(OUT_DIR / "07_pf_obligation.json", pf_obligation)

    pf_trace = {
        "certificate_id": pf_obligation.get("obligation_id", "PF-TRACE-RECON"),
        "obligation_id": pf_obligation.get("obligation_id"),
        "obligation_hash": pf_obligation.get("obligation_hash"),
        "source_record_id": record_data["record_id"],
        "decision_id": d["decision_id"],
        "enforcement_mode": pf_obligation.get("enforcement_mode"),
        "trace": {"steps": ["obligation_exported", "trace_bound_to_record"]},
    }
    _write_json(OUT_DIR / "08_pf_trace_certificate.json", pf_trace)

    context_with_trace = merge_pf_trace_into_context(context_data, pf_obligation)

    post_grant_decision: dict[str, Any] | None = None
    if scope_grant:
        regate = gate.evaluate_with_grant(
            ai_output=ai_output,
            requested_tool="lab_scheduler.prioritize",
            requested_action="prioritize_next_run",
            context=AKTAContext.from_dict(context_with_trace),
            deployment_profile="P2_analysis_assistant",
            domain_overlay="generic_lab_v0",
            scope_grant=scope_grant,
            record=record_data,
            trigger=trigger,
        )
        post_grant_decision = regate.to_dict()
        _write_json(OUT_DIR / "01_akta_decision_after_grant.json", post_grant_decision)

        # Case C: grant must not silently override weak-evidence P2 policy.
        assert post_grant_decision["admissibility"] in (
            "blocked",
            "review_required",
            "authorization_required",
        ), (
            "Case C: SCOPE grant must not silently pass when AKTA evidence/profile "
            f"still blocks; got {post_grant_decision['admissibility']}"
        )
        assert post_grant_decision["admissibility"] not in (
            "allowed",
            "allowed_with_logging",
            "draft_only",
        )
        print(
            "Case C (post-grant re-gate): "
            f"{post_grant_decision['admissibility']} — "
            f"{post_grant_decision.get('decision_reason', '')[:120]}"
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
    export_memory_entry(memory_entry, OUT_DIR / "10_scientific_memory_import.json")

    ltg_scenario = convert_labtrust_scenario({
        "scenario_id": "recon_demo_01",
        "prompt": "Queue prioritization after weak evidence review.",
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
    _write_json(OUT_DIR / "11_pcs_bench_report.json", bench_result)

    artifact_paths = {
        "00_vsa_report.json": OUT_DIR / "00_vsa_report.json",
        "01_akta_decision.json": OUT_DIR / "01_akta_decision.json",
        "02_akta_record.json": OUT_DIR / "02_akta_record.json",
        "03_review_trigger.json": OUT_DIR / "03_review_trigger.json",
        "06_scope_grant.json": OUT_DIR / "06_scope_grant.json",
        "09_pcs_bundle": pcs_dir,
    }
    linkage = _linkage_report(artifact_paths)

    readme = (
        "# Reconstructable Experiment (AKTA v0.7)\n\n"
        "Regenerate: `python scripts/demo_reconstructable_experiment.py`\n\n"
        f"SCOPE adapter mode: {adapter_mode}\n"
        f"Policy integrity mode: {gate.policy.integrity_mode}\n"
    )
    (OUT_DIR / "README.md").write_text(readme, encoding="utf-8")

    recon_md = "# Reconstruction Report\n\n"
    recon_md += "## SCOPE grant vs AKTA policy layers\n\n"
    recon_md += (
        "SCOPE grants scoped authorization; AKTA re-gate applies grant metadata then "
        "re-evaluates against deployment profile and evidence policy. Grants do not "
        "automatically override weak-evidence blocks unless policy explicitly allows.\n\n"
    )
    recon_md += f"- Case A (pre-grant): {d['admissibility']}\n"
    recon_md += f"- Case B (SCOPE grant): {approved_scope}\n"
    if post_grant_decision:
        recon_md += (
            f"- Case C (post-grant re-gate): {post_grant_decision['admissibility']} — "
            f"{post_grant_decision.get('decision_reason', '')}\n"
        )
    recon_md += f"- All linkage checks passed: {linkage['all_linked']}\n"
    for link in linkage["linkage"]:
        recon_md += f"- {link['from']} -> {link['to']} ({link['field']}): {'OK' if link['ok'] else 'FAIL'}\n"
    recon_md += f"- PCS-Bench: {bench_result['passed_count']}/{bench_result['total']} passed\n"
    (OUT_DIR / "reconstruction_report.md").write_text(recon_md, encoding="utf-8")

    print(f"Decision:       {d['admissibility']}")
    if post_grant_decision:
        print(f"Post-grant:     {post_grant_decision['admissibility']}")
    print(f"VSA claims:     {len(vsa_report.get('claims', []))}")
    print(f"PCS bundle:     {pcs_dir / 'manifest.json'}")
    print(f"Memory import:  {OUT_DIR / '10_scientific_memory_import.json'}")
    print(f"PCS-Bench:      {bench_result['passed_count']}/{bench_result['total']} passed")
    print(f"Linkage:        {'OK' if linkage['all_linked'] else 'FAILED'}")
    print(f"\nArtifacts in {OUT_DIR}")

    ok = linkage["all_linked"] and bench_result.get("passed", False)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run_demo())
