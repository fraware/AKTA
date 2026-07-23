"""AKTA 1.1 WS8: RequestedAuthorizationContext containment acceptance."""

from __future__ import annotations

from akta.capability_envelope import legacy_scope_to_envelope
from akta.requested_authorization import (
    build_requested_authorization_context,
    evaluate_authorization_containment,
    resolve_family_operation,
)


def _granted(**overrides):
    env = legacy_scope_to_envelope(
        approved_scope="protocol_draft",
        allowed_tools=["protocol_editor.draft_change"],
        blocked_tools=["robot_queue.submit"],
        target={"type": "protocol", "protocol_id": "protocol-v3"},
        environment={"tenant_id": "tenant-a"},
        responsibility_ceiling="R4_methodological_modification",
        cardinality={"mode": "single", "maximum_uses": 1, "maximum_items": 1},
        constraints={"protocol_version": "protocol-v3"},
    )
    env.update(overrides)
    return env


def test_a5_draft_vs_update_active_mapping() -> None:
    assert resolve_family_operation(
        action_class="A5_protocol_modification",
        requested_tool="protocol_editor.draft_change",
    ) == ("protocol", "draft")
    assert resolve_family_operation(
        action_class="A5_protocol_modification",
        requested_tool="protocol_editor.update_active_protocol",
    ) == ("protocol", "update_active")


def test_a7_queue_priority_mapping() -> None:
    assert resolve_family_operation(
        action_class="A7_resource_or_queue_prioritization",
        requested_tool="lab_scheduler.prioritize",
    ) == ("queue", "single_run_priority")


def test_a9_robot_mapping() -> None:
    assert resolve_family_operation(
        action_class="A9_execution_adjacent_or_external_action",
        requested_tool="robot_queue.submit",
    ) == ("queue", "robot_submit")


def test_rejects_broader_operation() -> None:
    granted = _granted()
    # Force update_active request against draft grant.
    requested = build_requested_authorization_context(
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_active",
        action_class="A5_protocol_modification",
        context={
            "protocol_version": "protocol-v3",
            "tenant_id": "tenant-a",
        },
        constraints_overrides={"protocol_version": "protocol-v3"},
    )
    result = evaluate_authorization_containment(
        granted_envelope=granted, requested=requested
    )
    assert not result.covers


def test_rejects_other_protocol() -> None:
    granted = _granted()
    requested = build_requested_authorization_context(
        requested_tool="protocol_editor.draft_change",
        action_class="A5_protocol_modification",
        context={"protocol_version": "protocol-v9", "tenant_id": "tenant-a"},
        constraints_overrides={"protocol_version": "protocol-v3"},
        target_overrides={"type": "protocol", "protocol_id": "protocol-v9"},
    )
    result = evaluate_authorization_containment(
        granted_envelope=granted, requested=requested
    )
    assert not result.covers


def test_rejects_other_tenant() -> None:
    granted = _granted()
    requested = build_requested_authorization_context(
        requested_tool="protocol_editor.draft_change",
        action_class="A5_protocol_modification",
        context={"protocol_version": "protocol-v3", "tenant_id": "tenant-b"},
        constraints_overrides={"protocol_version": "protocol-v3"},
        target_overrides={"type": "protocol", "protocol_id": "protocol-v3"},
        environment_overrides={"tenant_id": "tenant-b"},
    )
    result = evaluate_authorization_containment(
        granted_envelope=granted, requested=requested
    )
    assert not result.covers


def test_rejects_responsibility_ceiling() -> None:
    granted = _granted()
    requested = build_requested_authorization_context(
        requested_tool="protocol_editor.draft_change",
        action_class="A5_protocol_modification",
        context={"protocol_version": "protocol-v3", "tenant_id": "tenant-a"},
        constraints_overrides={"protocol_version": "protocol-v3"},
        target_overrides={"type": "protocol", "protocol_id": "protocol-v3"},
        responsibility_level="R6_physical_execution",
    )
    result = evaluate_authorization_containment(
        granted_envelope=granted, requested=requested
    )
    assert not result.covers


def test_rejects_item_count() -> None:
    granted = _granted()
    requested = build_requested_authorization_context(
        requested_tool="protocol_editor.draft_change",
        action_class="A5_protocol_modification",
        context={"protocol_version": "protocol-v3", "tenant_id": "tenant-a"},
        constraints_overrides={"protocol_version": "protocol-v3"},
        target_overrides={"type": "protocol", "protocol_id": "protocol-v3"},
        item_count=5,
    )
    result = evaluate_authorization_containment(
        granted_envelope=granted, requested=requested
    )
    assert not result.covers
    assert any("item_count" in e for e in result.errors)


def test_rejects_unknown_constraint() -> None:
    granted = _granted()
    requested = build_requested_authorization_context(
        requested_tool="protocol_editor.draft_change",
        action_class="A5_protocol_modification",
        context={"protocol_version": "protocol-v3", "tenant_id": "tenant-a"},
        constraints_overrides={"protocol_version": "protocol-v3", "evil_flag": True},
        target_overrides={"type": "protocol", "protocol_id": "protocol-v3"},
    )
    result = evaluate_authorization_containment(
        granted_envelope=granted, requested=requested
    )
    assert not result.covers
    assert any("unknown request constraint" in e for e in result.errors)


def test_rejects_no_remaining_use() -> None:
    granted = _granted()
    requested = build_requested_authorization_context(
        requested_tool="protocol_editor.draft_change",
        action_class="A5_protocol_modification",
        context={"protocol_version": "protocol-v3", "tenant_id": "tenant-a"},
        constraints_overrides={"protocol_version": "protocol-v3"},
        target_overrides={"type": "protocol", "protocol_id": "protocol-v3"},
    )
    result = evaluate_authorization_containment(
        granted_envelope=granted,
        requested=requested,
        ledger_status={"status": "active", "cardinality_remaining": 0},
    )
    assert not result.covers
    assert any("no remaining use" in e for e in result.errors)


def test_valid_success() -> None:
    granted = _granted()
    requested = build_requested_authorization_context(
        requested_tool="protocol_editor.draft_change",
        action_class="A5_protocol_modification",
        context={"protocol_version": "protocol-v3", "tenant_id": "tenant-a"},
        constraints_overrides={"protocol_version": "protocol-v3"},
        target_overrides={"type": "protocol", "protocol_id": "protocol-v3"},
        environment_overrides={"tenant_id": "tenant-a"},
        item_count=1,
        responsibility_level="R3_recommendation",
    )
    result = evaluate_authorization_containment(
        granted_envelope=granted,
        requested=requested,
        ledger_status={"status": "active", "cardinality_remaining": 1},
    )
    assert result.covers, result.errors
