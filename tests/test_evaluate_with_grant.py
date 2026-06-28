"""Closed-loop evaluate_with_grant semantics (v0.7)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from akta.review_loop import akta_cannot_broaden_grant

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def _active_protocol_trigger(gate: AKTAGate) -> tuple[dict, dict]:
    decision = gate.evaluate(
        ai_output={"summary": "Update active protocol threshold."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_threshold",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
    )
    d = decision.to_dict()
    record = decision.to_record().to_dict()
    record["review_trigger"] = d["review_trigger"]
    return d, record


def test_grant_allows_draft_change(gate: AKTAGate) -> None:
    d, record = _active_protocol_trigger(gate)
    trigger = d["review_trigger"]
    grant = {
        "authorization": {"approved_scope": "protocol_draft"},
        "source": {"requested_scope": trigger["requested_scope"]},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    regate = gate.evaluate_with_grant(
        ai_output={"summary": "Draft timing tweak."},
        requested_tool="protocol_editor.draft_change",
        requested_action="draft_timing",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
        scope_grant=grant,
        record=record,
        trigger=trigger,
    )
    assert regate.admissibility == "draft_only"


def test_grant_does_not_allow_active_update(gate: AKTAGate) -> None:
    d, record = _active_protocol_trigger(gate)
    trigger = d["review_trigger"]
    grant = {
        "authorization": {"approved_scope": "protocol_draft"},
        "source": {"requested_scope": trigger["requested_scope"]},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    regate = gate.evaluate_with_grant(
        ai_output={"summary": "Update threshold again."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_threshold",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
        scope_grant=grant,
        record=record,
        trigger=trigger,
    )
    assert regate.admissibility in ("review_required", "blocked")
    assert "protocol_editor.update_active_protocol" in regate.to_dict().get("blocked_tools", [])


def test_grant_expires_on_protocol_change(gate: AKTAGate) -> None:
    d, record = _active_protocol_trigger(gate)
    trigger = d["review_trigger"]
    record["scientific_context"] = {"protocol_version": "PROTO-V1"}
    grant = {
        "authorization": {"approved_scope": "protocol_draft"},
        "source": {"requested_scope": trigger["requested_scope"]},
    }
    regate = gate.evaluate_with_grant(
        ai_output={"summary": "Draft tweak after protocol change."},
        requested_tool="protocol_editor.draft_change",
        requested_action="draft_timing",
        context=AKTAContext.from_dict({
            "evidence_state": "E4_internally_consistent_evidence",
            "protocol_version": "PROTO-V2",
        }),
        deployment_profile="P4_protocol_drafting_assistant",
        scope_grant=grant,
        record=record,
        trigger=trigger,
    )
    assert regate.admissibility == "review_required"


def test_grant_expires_on_evidence_downgrade(gate: AKTAGate) -> None:
    d, record = _active_protocol_trigger(gate)
    trigger = d["review_trigger"]
    record["classification"] = {"evidence_state": "E4_internally_consistent_evidence"}
    grant = {
        "authorization": {"approved_scope": "protocol_draft"},
        "source": {"requested_scope": trigger["requested_scope"]},
    }
    regate = gate.evaluate_with_grant(
        ai_output={"summary": "Draft after evidence downgrade."},
        requested_tool="protocol_editor.draft_change",
        requested_action="draft_timing",
        context=AKTAContext.from_dict({"evidence_state": "E2_preliminary_signal"}),
        deployment_profile="P4_protocol_drafting_assistant",
        scope_grant=grant,
        record=record,
        trigger=trigger,
    )
    assert regate.admissibility == "review_required"


def test_grant_requires_re_review_for_new_tool(gate: AKTAGate) -> None:
    d, record = _active_protocol_trigger(gate)
    trigger = d["review_trigger"]
    grant = {
        "authorization": {
            "approved_scope": "protocol_draft",
            "allowed_tools": ["protocol_editor.draft_change"],
        },
        "source": {"requested_scope": trigger["requested_scope"]},
    }
    regate = gate.evaluate_with_grant(
        ai_output={"summary": "Try robot submit with narrow grant."},
        requested_tool="robot_queue.submit",
        requested_action="submit_run",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P6_authorized_closed_loop_lab_agent",
        scope_grant=grant,
        record=record,
        trigger=trigger,
    )
    assert regate.admissibility in ("blocked", "review_required", "authorization_required")
    assert "robot_queue.submit" in regate.to_dict().get("blocked_tools", [])


def test_akta_cannot_upgrade_scope_from_protocol_draft_to_robot_submit() -> None:
    assert akta_cannot_broaden_grant("protocol_draft", "robot_queue_submission") is True
    assert akta_cannot_broaden_grant("protocol_draft", "protocol_draft") is False


def test_grant_preserves_trigger_blocked_tools(gate: AKTAGate) -> None:
    d, record = _active_protocol_trigger(gate)
    trigger = d["review_trigger"]
    assert "protocol_editor.update_active_protocol" in trigger.get("blocked_tools", [])

    grant = {
        "authorization": {"approved_scope": "protocol_draft"},
        "source": {"requested_scope": trigger["requested_scope"]},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    regate = gate.evaluate_with_grant(
        ai_output={"summary": "Draft timing tweak."},
        requested_tool="protocol_editor.draft_change",
        requested_action="draft_timing",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
        scope_grant=grant,
        record=record,
        trigger=trigger,
    )
    blocked = regate.to_dict().get("blocked_tools", [])
    assert "protocol_editor.update_active_protocol" in blocked
    for tool in trigger.get("blocked_tools", []):
        assert tool in blocked
