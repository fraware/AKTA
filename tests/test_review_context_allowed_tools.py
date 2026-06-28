"""Tests for prior_review_allowed_tools enforcement (P0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from akta.review_context import evaluate_prior_review
from akta.review_decision import scope_grant_to_context_metadata
from akta.tool_registry import ToolRegistry

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def tool_registry() -> ToolRegistry:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    return gate.tool_registry


def _prior_metadata(**overrides: object) -> dict[str, object]:
    base = {
        "prior_review_id": "SCOPE-GRANT-ALLOWLIST",
        "prior_review_scope": "protocol_draft",
        "prior_review_decision": "approved",
        "prior_review_expired": False,
        "prior_review_allowed_tools": ["protocol_editor.draft_change"],
    }
    base.update(overrides)
    return base


def test_allowed_tools_permits_draft_change(tool_registry: ToolRegistry) -> None:
    spec = tool_registry.resolve("protocol_editor.draft_change")
    layer = evaluate_prior_review(
        _prior_metadata(),
        spec.action_type,
        "protocol_editor.draft_change",
        spec,
    )
    assert layer is None


def test_allowed_tools_blocks_active_protocol_update(tool_registry: ToolRegistry) -> None:
    spec = tool_registry.resolve("protocol_editor.update_active_protocol")
    layer = evaluate_prior_review(
        _prior_metadata(),
        spec.action_type,
        "protocol_editor.update_active_protocol",
        spec,
    )
    assert layer is not None
    assert layer.decision == "blocked"
    assert "protocol_editor.update_active_protocol" in layer.reason


def test_allowed_tools_blocks_robot_queue_submit(tool_registry: ToolRegistry) -> None:
    spec = tool_registry.resolve("robot_queue.submit")
    layer = evaluate_prior_review(
        _prior_metadata(),
        spec.action_type,
        "robot_queue.submit",
        spec,
    )
    assert layer is not None
    assert layer.decision == "blocked"


def test_same_rank_unlisted_tool_blocked(tool_registry: ToolRegistry) -> None:
    spec = tool_registry.resolve("publication.draft_claim")
    layer = evaluate_prior_review(
        _prior_metadata(),
        spec.action_type,
        "publication.draft_claim",
        spec,
    )
    assert layer is not None
    assert layer.decision == "blocked"


def test_expired_grant_requires_review(tool_registry: ToolRegistry) -> None:
    spec = tool_registry.resolve("protocol_editor.draft_change")
    layer = evaluate_prior_review(
        _prior_metadata(prior_review_expired=True),
        spec.action_type,
        "protocol_editor.draft_change",
        spec,
    )
    assert layer is not None
    assert layer.decision == "review_required"


def test_denied_grant_blocks(tool_registry: ToolRegistry) -> None:
    spec = tool_registry.resolve("protocol_editor.draft_change")
    layer = evaluate_prior_review(
        _prior_metadata(prior_review_decision="denied"),
        spec.action_type,
        "protocol_editor.draft_change",
        spec,
    )
    assert layer is not None
    assert layer.decision == "blocked"


def test_scope_grant_to_context_metadata_copies_allowed_tools() -> None:
    grant = {
        "grant_id": "SCOPE-GRANT-META01",
        "authorization": {
            "approved_scope": "protocol_draft",
            "allowed_tools": ["protocol_editor.draft_change"],
            "expires_at": "2030-01-01T00:00:00Z",
        },
        "source": {"requested_scope": "active_protocol_update"},
        "provenance": {"scope_policy_version": "scope-core-v0.7"},
    }
    metadata = scope_grant_to_context_metadata(grant)
    assert metadata["prior_review_allowed_tools"] == ["protocol_editor.draft_change"]
    assert metadata["prior_review_grant_id"] == "SCOPE-GRANT-META01"
    assert metadata["prior_review_provenance"]["scope_policy_version"] == "scope-core-v0.7"


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_evaluate_with_grant_honors_allowed_tools(gate: AKTAGate) -> None:
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
    trigger = d["review_trigger"]
    record["review_trigger"] = trigger
    grant = {
        "grant_id": "SCOPE-GRANT-ALLOWED-ONLY",
        "authorization": {
            "approved_scope": "protocol_draft",
            "allowed_tools": ["protocol_editor.draft_change"],
        },
        "source": {"requested_scope": trigger["requested_scope"]},
    }
    allowed = gate.evaluate_with_grant(
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
    blocked = gate.evaluate_with_grant(
        ai_output={"summary": "Try active update with allowlist grant."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_threshold",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
        scope_grant=grant,
        record=record,
        trigger=trigger,
    )
    assert allowed.admissibility == "draft_only"
    assert blocked.admissibility in ("blocked", "review_required")
    assert "protocol_editor.update_active_protocol" in blocked.to_dict().get("blocked_tools", [])
