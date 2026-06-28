"""Integrated AKTA x SCOPE protocol-drift demo (v0.5).

Flow:
  active protocol update -> AKTA review_required (requested_scope=active_protocol_update)
  -> SCOPE adapter (simulated | python-import | cli) -> packet, decision, grant
  -> draft_change allowed; active update + robot blocked -> PF + PCS full-chain export
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

DEMO_TIMESTAMP = "2026-06-28T12:00:00Z"
DEMO_DECISION_ID = "AKTA-DEC-DRIFT0001"
DEMO_RECORD_ID = "AKTA-SAR-DRIFT0001"
DEMO_REVIEW_TRIGGER_ID = "AKTA-REVTRIG-DRIFT0001"
DEMO_DRAFT_DECISION_ID = "AKTA-DEC-DRIFT0002"
DEMO_DRAFT_RECORD_ID = "AKTA-SAR-DRIFT0002"


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


def stabilize_record(record: dict[str, Any], *, record_id: str, timestamp: str = DEMO_TIMESTAMP) -> dict[str, Any]:
    record = dict(record)
    record["record_id"] = record_id
    record["timestamp"] = timestamp
    return _rehash_record(record)


def _format_scope_grant(scope_grant: dict[str, Any]) -> str:
    approved = scope_grant.get("granted_scope") or scope_grant.get("authorization", {}).get(
        "approved_scope"
    )
    if approved:
        return str(approved)
    return json.dumps(scope_grant)


def run_demo() -> int:
    from akta import AKTAGate, AKTAContext
    from akta.records import AKTARecord, AKTADecision
    from adapters.pcs.export_artifact import export_pcs_bundle
    from adapters.pf_core.export_obligation import export_pf_obligation
    from adapters.scope.client import detect_adapter_mode, submit_review_trigger

    demo_dir = ROOT / "examples" / "integrated_protocol_drift"
    demo_dir.mkdir(parents=True, exist_ok=True)
    pcs_dir = demo_dir / "pcs_bundle"

    adapter_mode = detect_adapter_mode()
    mode_label = {
        "simulated": "simulated (contract simulation only)",
        "python-import": "python-import (SCOPE_REPO_PATH sibling repo)",
        "cli": "cli (SCOPE_CLI subprocess)",
    }.get(adapter_mode, adapter_mode)
    print(f"=== AKTA v0.5 Demo: Integrated Protocol Drift (AKTA x SCOPE) ===")
    print(f"SCOPE adapter mode: {mode_label}\n")

    context_data = json.loads((demo_dir / "context.json").read_text(encoding="utf-8"))
    ai_output = json.loads((demo_dir / "ai_output.json").read_text(encoding="utf-8"))

    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")

    active_decision = gate.evaluate(
        ai_output=ai_output,
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_temperature_threshold",
        context=AKTAContext.from_dict(context_data),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
    )
    active_d = stabilize_decision(
        active_decision.to_dict(),
        decision_id=DEMO_DECISION_ID,
        record_id=DEMO_RECORD_ID,
        review_trigger_id=DEMO_REVIEW_TRIGGER_ID,
    )
    assert active_d["admissibility"] == "review_required"
    assert active_d["review_trigger"]["requested_scope"] == "active_protocol_update"

    AKTADecision(active_d).save(demo_dir / "akta_decision_active_update.json")
    active_record = stabilize_record(
        active_decision.to_record(ai_output=ai_output, context=context_data).to_dict(),
        record_id=DEMO_RECORD_ID,
    )
    active_record["review_trigger"] = active_d["review_trigger"]
    AKTARecord(active_record).save(demo_dir / "akta_record_active_update.json")

    scope_result = submit_review_trigger(
        active_d["review_trigger"],
        record=active_record,
        grant_scope="protocol_draft",
        reviewer_id="protocol_owner",
    )
    if scope_result.error:
        print(f"SCOPE adapter error (invalid grant blocks PCS export): {scope_result.error}")
        return 1

    scope_packet = scope_result.review_packet or {}
    scope_grant = scope_result.grant or {}
    scope_decision = scope_result.decision or {}
    (demo_dir / "scope_review_packet.json").write_text(
        json.dumps(scope_packet, indent=2), encoding="utf-8"
    )
    (demo_dir / "scope_narrow_grant.json").write_text(
        json.dumps(scope_grant, indent=2), encoding="utf-8"
    )
    (demo_dir / "scope_decision.json").write_text(
        json.dumps(scope_decision, indent=2), encoding="utf-8"
    )
    (demo_dir / "review_trigger.json").write_text(
        json.dumps(active_d["review_trigger"], indent=2), encoding="utf-8"
    )

    draft_decision = gate.evaluate(
        ai_output={"summary": "Draft protocol threshold change for owner review."},
        requested_tool="protocol_editor.draft_change",
        requested_action="draft_threshold_change",
        context=AKTAContext.from_dict(context_data),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
    )
    draft_d = stabilize_decision(
        draft_decision.to_dict(),
        decision_id=DEMO_DRAFT_DECISION_ID,
        record_id=DEMO_DRAFT_RECORD_ID,
    )
    assert draft_d["admissibility"] == "draft_only"
    assert "protocol_editor.draft_change" in draft_d.get("allowed_tools", [])
    AKTADecision(draft_d).save(demo_dir / "akta_decision_draft_only.json")

    robot_decision = gate.evaluate(
        ai_output={"summary": "Submit run after protocol tweak."},
        requested_tool="robot_queue.submit",
        requested_action="submit_run",
        context=AKTAContext.from_dict(context_data),
        deployment_profile="P5_review_gated_experimental_planner",
        domain_overlay="generic_lab_v0",
    )
    assert robot_decision.admissibility in ("blocked", "authorization_required")

    pf_path = export_pf_obligation(
        AKTARecord(active_record), demo_dir, validate=True, decision_id=active_d["decision_id"]
    )
    pf_obligation = json.loads(pf_path.read_text(encoding="utf-8"))
    (demo_dir / "pf_obligation.json").write_text(json.dumps(pf_obligation, indent=2), encoding="utf-8")
    if pf_path.name != "pf_obligation.json":
        pf_path.unlink(missing_ok=True)

    export_pcs_bundle(
        AKTARecord(active_record),
        pcs_dir,
        decision=active_d,
        scope_review_packet=scope_packet,
        scope_decision=scope_decision,
        scope_grant=scope_grant,
        pf_obligation=pf_obligation,
        validate=True,
    )

    print(f"Active update:  {active_d['admissibility']} scope={active_d['review_trigger']['requested_scope']}")
    print(f"Draft follow-up: {draft_d['admissibility']} (draft_change allowed)")
    print(f"Robot submit:   {robot_decision.admissibility} (still blocked/authorization)")
    print(f"SCOPE grant:    {_format_scope_grant(scope_grant)}")
    print(f"SCOPE decision: {scope_decision.get('status', scope_decision)}")
    print(f"PF obligation:  {pf_obligation['obligation_type']}")
    print(f"PCS bundle:     {pcs_dir / 'manifest.json'}")
    print(f"Adapter mode:   {mode_label}")
    print(f"Artifacts in {demo_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(run_demo())
