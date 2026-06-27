"""PF-Core export contract integration tests (v0.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from adapters.pf_core.export_obligation import build_pf_obligation, export_pf_obligation
from akta.records import validate_against_schema

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


@pytest.mark.parametrize(
    "tool,action,profile,evidence,expected_decision",
    [
        ("lab_scheduler.prioritize", "prioritize", "P2_analysis_assistant", "E2_preliminary_signal", "blocked"),
        ("experiment_planner.create_run_plan", "plan", "P5_review_gated_experimental_planner", "E5_internally_replicated_evidence", "review_required"),
        ("lab_scheduler.prioritize", "prioritize", "P6_authorized_closed_loop_lab_agent", "E6_independently_reproduced_evidence", "authorization_required"),
        ("experiment_planner.create_validation_draft", "draft", "P3_review_gated_evidence_interpreter", "E2_preliminary_signal", "draft_only"),
    ],
)
def test_pf_obligation_contract(
    gate: AKTAGate,
    tmp_path: Path,
    tool: str,
    action: str,
    profile: str,
    evidence: str,
    expected_decision: str,
) -> None:
    ctx = {"evidence_state": evidence, "domain": "materials"}
    overlay = "generic_lab_v0" if "prioritize" in tool else None
    decision = gate.evaluate(
        ai_output={"summary": f"Test {action}."},
        requested_tool=tool,
        requested_action=action,
        context=AKTAContext.from_dict(ctx),
        deployment_profile=profile,
        domain_overlay=overlay,
    )
    record = decision.to_record()
    obligation = build_pf_obligation(record.to_dict(), decision_id=decision.to_dict()["decision_id"])
    validate_against_schema(obligation, "pf_core_obligation.schema.json")
    assert obligation["decision"] == expected_decision
    assert obligation["obligation_hash"].startswith("sha256:")
    assert obligation["required_runtime_behavior"]["block_execution"] == (expected_decision in ("blocked", "abstain_insufficient_context"))

    path = export_pf_obligation(record, tmp_path, decision_id=decision.to_dict()["decision_id"])
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["obligation_id"].startswith("PF-OBL-")
