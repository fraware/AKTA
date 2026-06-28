"""PF-Core obligation contract tests with pinned fixtures (v0.4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from adapters.pf_core.export_obligation import build_pf_obligation
from akta.records import validate_against_schema

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_pf_obligation_matches_pinned_fixture(gate: AKTAGate) -> None:
    pinned = json.loads((FIXTURES / "pf_obligation_review_required.json").read_text(encoding="utf-8"))
    decision = gate.evaluate(
        ai_output={"summary": "Update active protocol threshold."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_threshold",
        context=AKTAContext.from_dict({
            "evidence_state": "E4_internally_consistent_evidence",
            "validation_status": "V3_preliminary_experimental_support",
        }),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
    )
    record = decision.to_record().to_dict()
    obligation = build_pf_obligation(record, decision_id=decision.to_dict()["decision_id"])
    validate_against_schema(obligation, "pf_core_obligation.schema.json")

    for field in (
        "obligation_id",
        "obligation_type",
        "decision",
        "enforcement_mode",
        "source",
        "source_record_id",
        "decision_id",
        "blocked_tools",
        "allowed_tools",
        "policy_hash",
        "tool_registry_hash",
        "required_runtime_behavior",
        "obligation_hash",
    ):
        assert field in obligation, f"missing {field}"
        assert obligation[field] is not None or field == "domain_overlay_hash"

    for field in (
        "obligation_type",
        "decision",
        "enforcement_mode",
        "source",
    ):
        assert obligation[field] == pinned[field]
    assert obligation["required_runtime_behavior"]["require_review_before_tool_call"] is True
    assert "protocol_editor.update_active_protocol" in obligation["blocked_tools"]


def test_pf_authorization_obligation(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Submit run."},
        requested_tool="robot_queue.submit",
        requested_action="submit_run",
        context=AKTAContext.from_dict({
            "evidence_state": "E6_independently_reproduced_evidence",
        }),
        deployment_profile="P6_authorized_closed_loop_lab_agent",
    )
    record = decision.to_record().to_dict()
    obligation = build_pf_obligation(record, decision_id=decision.to_dict()["decision_id"])
    validate_against_schema(obligation, "pf_core_obligation.schema.json")
    assert obligation["decision"] == "authorization_required"
    assert obligation["required_runtime_behavior"]["require_authorization_before_tool_call"] is True
