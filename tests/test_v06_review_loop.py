"""Tests for v0.6 closed-loop review, expiry, and scoped re-gate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from akta.review_decision import (
    apply_scope_grant_to_context,
    enforce_grant_expiry,
    is_review_expired,
    load_review_decision,
    process_review_loop,
)
from akta.review_packet import export_human_review_packet, import_completed_review

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_review_expiry_enforcement() -> None:
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    assert is_review_expired(past) is True
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    assert is_review_expired(future) is False


def test_scope_grant_narrow_allows_draft(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Update active protocol threshold."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_threshold",
        context=AKTAContext.from_dict({
            "evidence_state": "E4_internally_consistent_evidence",
        }),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
    )
    assert decision.admissibility == "review_required"
    trigger = decision.to_dict()["review_trigger"]

    scope_grant = {
        "grant_id": "GRANT-TEST-001",
        "granted_scope": "protocol_draft",
        "requested_scope": "active_protocol_update",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }

    regate = gate.evaluate_with_grant(
        ai_output={"summary": "Draft timing tweak."},
        requested_tool="protocol_editor.draft_change",
        requested_action="draft_timing",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
        scope_grant=scope_grant,
        trigger=trigger,
    )
    assert regate.admissibility == "draft_only"


def test_expired_grant_triggers_review(gate: AKTAGate) -> None:
    ctx = apply_scope_grant_to_context(
        {},
        {
            "granted_scope": "protocol_draft",
            "requested_scope": "active_protocol_update",
            "expires_at": "2020-01-01T00:00:00Z",
        },
        validate_grant=False,
    )
    ctx = enforce_grant_expiry(ctx)
    assert ctx["metadata"]["prior_review_expired"] is True

    decision = gate.evaluate(
        ai_output={"summary": "Draft change."},
        requested_tool="protocol_editor.draft_change",
        requested_action="draft_timing",
        context=AKTAContext.from_dict(ctx),
        deployment_profile="P4_protocol_drafting_assistant",
    )
    assert decision.admissibility in ("review_required", "draft_only", "blocked")


def test_human_review_packet_export(gate: AKTAGate) -> None:
    decision = gate.evaluate(
        ai_output={"summary": "Update active protocol threshold."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_threshold",
        context=AKTAContext.from_dict({
            "evidence_state": "E4_internally_consistent_evidence",
        }),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
    )
    d = decision.to_dict()
    assert d.get("review_trigger")
    packet = export_human_review_packet(d["review_trigger"], decision=d)
    assert packet["packet_type"] == "akta_human_review_packet"
    assert packet.get("human_summary")


def test_import_completed_review() -> None:
    review_decision = {
        "review_decision_id": "REV-001",
        "review_trigger_id": "TRIG-001",
        "decision": "approved",
        "granted_scope": "protocol_draft",
        "reviewer_id": "protocol_owner",
        "expires_at": "2030-01-01T00:00:00Z",
    }
    ctx = import_completed_review(review_decision)
    assert ctx["metadata"]["prior_review_scope"] == "protocol_draft"


def test_process_review_loop_with_grant(gate: AKTAGate) -> None:
    initial = gate.evaluate(
        ai_output={"summary": "Update threshold."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_threshold",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P4_protocol_drafting_assistant",
    )
    trigger = initial.to_dict()["review_trigger"]
    grant = {
        "granted_scope": "protocol_draft",
        "requested_scope": trigger["requested_scope"],
        "expires_at": "2030-01-01T00:00:00Z",
    }
    result = process_review_loop(
        gate,
        ai_output={"summary": "Draft timing."},
        requested_tool="protocol_editor.draft_change",
        requested_action="draft_timing",
        context={"evidence_state": "E4_internally_consistent_evidence"},
        deployment_profile="P4_protocol_drafting_assistant",
        scope_grant=grant,
        trigger=trigger,
    )
    assert result.admissibility == "draft_only"
