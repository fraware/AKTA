"""AKTA 1.2 P0-3/4: RequestedAuthorizationContext containment (independent facts)."""

from __future__ import annotations

import pytest

from akta.capability_envelope import legacy_scope_to_envelope
from akta.errors import InsufficientAuthorizationContext
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
        environment={"tenant_id": "tenant-a", "project_id": "project-123"},
        responsibility_ceiling="R4_methodological_modification",
        cardinality={"mode": "single", "maximum_uses": 1, "maximum_items": 1},
        constraints={"protocol_version": "protocol-v3"},
    )
    env.update(overrides)
    return env


def _base_context(**extra):
    ctx = {
        "protocol_version": "protocol-v3",
        "tenant_id": "tenant-a",
        "project_id": "project-123",
    }
    ctx.update(extra)
    return ctx


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


def test_rejects_incomplete_context_no_defaults() -> None:
    with pytest.raises(InsufficientAuthorizationContext) as excinfo:
        build_requested_authorization_context(
            requested_tool="protocol_editor.draft_change",
            action_class="A5_protocol_modification",
            context={},
            mode="pilot",
        )
    assert "tenant_id" in excinfo.value.missing or "protocol_id" in excinfo.value.missing


def test_rejects_tool_heuristics_without_migration() -> None:
    with pytest.raises(InsufficientAuthorizationContext):
        resolve_family_operation(
            requested_tool="unknown_protocol_thing",
            mode="pilot",
            allow_migration_fallbacks=False,
        )


def test_migration_heuristics_only_when_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKTA_ALLOW_AUTH_MIGRATION_FALLBACKS", "1")
    monkeypatch.setenv("AKTA_RUNTIME_AUTHORIZATION", "disabled")
    monkeypatch.setenv("AKTA_REQUEST_MODE", "development")
    family, operation = resolve_family_operation(
        requested_tool="custom_protocol_helper",
        mode="development",
    )
    assert (family, operation) == ("protocol", "draft")


def test_rejects_broader_operation() -> None:
    granted = _granted()
    requested = build_requested_authorization_context(
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update_active",
        action_class="A5_protocol_modification",
        context=_base_context(),
        constraints_overrides={"protocol_version": "protocol-v3"},
        responsibility_level="R3_recommendation",
        item_count=1,
    )
    result = evaluate_authorization_containment(
        granted_envelope=granted, requested=requested
    )
    assert not result.covers
    assert result.reason_code in {
        "operation_not_covered",
        "tool_not_allowed",
    }


def test_rejects_other_protocol() -> None:
    granted = _granted()
    requested = build_requested_authorization_context(
        requested_tool="protocol_editor.draft_change",
        action_class="A5_protocol_modification",
        context=_base_context(protocol_version="protocol-v9"),
        constraints_overrides={"protocol_version": "protocol-v3"},
        target_overrides={"type": "protocol", "protocol_id": "protocol-v9"},
        responsibility_level="R3_recommendation",
        item_count=1,
    )
    result = evaluate_authorization_containment(
        granted_envelope=granted, requested=requested
    )
    assert not result.covers
    assert result.reason_code == "target_not_covered"


def test_rejects_other_tenant() -> None:
    granted = _granted()
    requested = build_requested_authorization_context(
        requested_tool="protocol_editor.draft_change",
        action_class="A5_protocol_modification",
        context=_base_context(tenant_id="tenant-b"),
        constraints_overrides={"protocol_version": "protocol-v3"},
        target_overrides={"type": "protocol", "protocol_id": "protocol-v3"},
        environment_overrides={"tenant_id": "tenant-b", "project_id": "project-123"},
        responsibility_level="R3_recommendation",
        item_count=1,
    )
    result = evaluate_authorization_containment(
        granted_envelope=granted, requested=requested
    )
    assert not result.covers
    assert result.reason_code == "environment_not_covered"


def test_rejects_responsibility_ceiling() -> None:
    granted = _granted()
    requested = build_requested_authorization_context(
        requested_tool="protocol_editor.draft_change",
        action_class="A5_protocol_modification",
        context=_base_context(),
        constraints_overrides={"protocol_version": "protocol-v3"},
        target_overrides={"type": "protocol", "protocol_id": "protocol-v3"},
        responsibility_level="R6_physical_execution",
        item_count=1,
    )
    result = evaluate_authorization_containment(
        granted_envelope=granted, requested=requested
    )
    assert not result.covers
    assert result.reason_code == "responsibility_exceeded"


def test_rejects_item_count() -> None:
    granted = _granted()
    requested = build_requested_authorization_context(
        requested_tool="protocol_editor.draft_change",
        action_class="A5_protocol_modification",
        context=_base_context(),
        constraints_overrides={"protocol_version": "protocol-v3"},
        target_overrides={"type": "protocol", "protocol_id": "protocol-v3"},
        responsibility_level="R3_recommendation",
        item_count=5,
    )
    result = evaluate_authorization_containment(
        granted_envelope=granted, requested=requested
    )
    assert not result.covers
    assert result.reason_code == "cardinality_exceeded"
    assert any("cardinality" in e or "item_count" in e for e in result.errors)


def test_does_not_copy_grant_blocked_tools_into_request() -> None:
    granted = _granted()
    requested = build_requested_authorization_context(
        requested_tool="protocol_editor.draft_change",
        action_class="A5_protocol_modification",
        context=_base_context(),
        constraints_overrides={"protocol_version": "protocol-v3"},
        target_overrides={"type": "protocol", "protocol_id": "protocol-v3"},
        responsibility_level="R3_recommendation",
        item_count=1,
    )
    result = evaluate_authorization_containment(
        granted_envelope=granted, requested=requested
    )
    assert result.covers, result.errors
    # Request facts must not inherit grant blocked_tools / expiration.
    action = requested.to_request_action()
    assert "blocked_tools" not in action
    assert "expiration" not in action
    if result.requested_envelope is not None:
        assert result.requested_envelope.get("blocked_tools") == []


def test_rejects_blocked_tool_via_grant_list() -> None:
    granted = _granted(
        allowed_tools=["protocol_editor.draft_change"],
        blocked_tools=["protocol_editor.draft_change"],
    )
    requested = build_requested_authorization_context(
        requested_tool="protocol_editor.draft_change",
        action_class="A5_protocol_modification",
        context=_base_context(),
        target_overrides={"type": "protocol", "protocol_id": "protocol-v3"},
        responsibility_level="R3_recommendation",
        item_count=1,
        constraints_overrides={},
    )
    # Clear grant constraints so exact protocol_version soft-match is irrelevant.
    granted["constraints"] = {}
    result = evaluate_authorization_containment(
        granted_envelope=granted, requested=requested
    )
    assert not result.covers
    assert result.reason_code == "tool_blocked"


def test_rejects_no_remaining_use() -> None:
    granted = _granted()
    granted["constraints"] = {}
    requested = build_requested_authorization_context(
        requested_tool="protocol_editor.draft_change",
        action_class="A5_protocol_modification",
        context=_base_context(),
        target_overrides={"type": "protocol", "protocol_id": "protocol-v3"},
        responsibility_level="R3_recommendation",
        item_count=1,
    )
    result = evaluate_authorization_containment(
        granted_envelope=granted,
        requested=requested,
        ledger_status={"status": "active", "cardinality_remaining": 0},
    )
    assert not result.covers
    assert result.reason_code == "cardinality_exhausted"
    assert any("no remaining use" in e for e in result.errors)


def test_valid_success() -> None:
    granted = _granted()
    granted["constraints"] = {}
    requested = build_requested_authorization_context(
        requested_tool="protocol_editor.draft_change",
        action_class="A5_protocol_modification",
        context=_base_context(),
        target_overrides={"type": "protocol", "protocol_id": "protocol-v3"},
        environment_overrides={"tenant_id": "tenant-a", "project_id": "project-123"},
        item_count=1,
        responsibility_level="R3_recommendation",
    )
    result = evaluate_authorization_containment(
        granted_envelope=granted,
        requested=requested,
        ledger_status={"status": "active", "cardinality_remaining": 1},
    )
    assert result.covers, result.errors
    assert result.comparator == "request_contained_by_envelope"


def test_release_mode_requires_contracts_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AKTA_REQUEST_MODE", "release")
    monkeypatch.delenv("AKTA_ALLOW_AUTH_MIGRATION_FALLBACKS", raising=False)
    import akta.contracts_runtime_api as api

    monkeypatch.setattr(api, "_import_contracts_attr", lambda _name: None)
    with pytest.raises(ImportError, match="request_contained_by_envelope"):
        api.request_contained_by_envelope(
            {
                "family": "protocol",
                "operation": "draft",
                "allowed_tools": ["protocol_editor.draft_change"],
                "blocked_tools": [],
                "target": {"type": "protocol", "protocol_id": "protocol-v3"},
                "environment": {"tenant_id": "tenant-a"},
                "responsibility_ceiling": "R4_methodological_modification",
                "cardinality": {"mode": "single", "maximum_uses": 1, "maximum_items": 1},
                "constraints": {},
                "expiration": {},
            },
            {
                "family": "protocol",
                "operation": "draft",
                "requested_tool": "protocol_editor.draft_change",
                "target": {"type": "protocol", "protocol_id": "protocol-v3"},
                "environment": {"tenant_id": "tenant-a"},
                "responsibility_level": "R3_recommendation",
                "item_count": 1,
            },
            mode="release",
        )
