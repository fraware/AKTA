"""Tests for prior_review_blocked_tools enforcement (P0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from akta.review_context import evaluate_prior_review
from akta.review_decision import scope_grant_to_context_metadata
from akta.tool_registry import ToolRegistry
from adapters.pcs.export_artifact import export_pcs_bundle
from akta.records import AKTARecord

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def tool_registry() -> ToolRegistry:
    gate = AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")
    return gate.tool_registry


def _prior_metadata(**overrides: object) -> dict[str, object]:
    base = {
        "prior_review_id": "SCOPE-GRANT-BLOCKLIST",
        "prior_review_scope": "single_run_queue_priority",
        "prior_review_decision": "approved",
        "prior_review_expired": False,
        "prior_review_blocked_tools": [
            "lab_scheduler.prioritize",
            "robot_queue.submit",
        ],
    }
    base.update(overrides)
    return base


def test_blocked_tools_blocks_listed_tool(tool_registry: ToolRegistry) -> None:
    spec = tool_registry.resolve("lab_scheduler.prioritize")
    layer = evaluate_prior_review(
        _prior_metadata(),
        spec.action_type,
        "lab_scheduler.prioritize",
        spec,
    )
    assert layer is not None
    assert layer.decision == "blocked"
    assert "lab_scheduler.prioritize" in layer.reason


def test_blocked_tools_allows_unlisted_tool(tool_registry: ToolRegistry) -> None:
    spec = tool_registry.resolve("protocol_editor.draft_change")
    layer = evaluate_prior_review(
        _prior_metadata(),
        spec.action_type,
        "protocol_editor.draft_change",
        spec,
    )
    assert layer is None


def test_scope_grant_to_context_metadata_copies_blocked_tools() -> None:
    grant = {
        "grant_id": "SCOPE-GRANT-BLOCKED01",
        "authorization": {
            "approved_scope": "single_run_queue_priority",
            "blocked_tools": ["lab_scheduler.prioritize"],
        },
        "source": {"requested_scope": "single_run_queue_priority"},
    }
    metadata = scope_grant_to_context_metadata(grant)
    assert metadata["prior_review_blocked_tools"] == ["lab_scheduler.prioritize"]


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def _queue_priority_fixture(gate: AKTAGate) -> tuple[dict, dict, dict]:
    decision = gate.evaluate(
        ai_output={"summary": "Prioritize next run."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_next_run",
        context=AKTAContext.from_dict({
            "evidence_state": "E5_internally_replicated_evidence",
            "validation_status": "V5_independently_replicated",
        }),
        deployment_profile="P5_review_gated_experimental_planner",
        domain_overlay="generic_lab_v0",
    )
    d = decision.to_dict()
    record = decision.to_record().to_dict()
    trigger = d["review_trigger"]
    record["review_trigger"] = trigger
    return d, record, trigger


def test_evaluate_with_grant_blocks_grant_blocked_tools(gate: AKTAGate) -> None:
    d, record, trigger = _queue_priority_fixture(gate)
    grant = {
        "grant_id": "SCOPE-GRANT-BLOCKLIST-REGATE",
        "authorization": {
            "approved_scope": "single_run_queue_priority",
            "blocked_tools": ["lab_scheduler.prioritize"],
        },
        "source": {"requested_scope": trigger["requested_scope"]},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    regate = gate.evaluate_with_grant(
        ai_output={"summary": "Prioritize after grant with blocked tool list."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_next_run",
        context=AKTAContext.from_dict({
            "evidence_state": "E5_internally_replicated_evidence",
            "validation_status": "V5_independently_replicated",
        }),
        deployment_profile="P5_review_gated_experimental_planner",
        domain_overlay="generic_lab_v0",
        scope_grant=grant,
        record=record,
        trigger=trigger,
    )
    assert regate.admissibility == "blocked"
    assert "lab_scheduler.prioritize" in regate.to_dict().get("blocked_tools", [])


def test_pcs_bundle_contains_grant_and_regate_decision(
    gate: AKTAGate,
    tmp_path: Path,
) -> None:
    d, record, trigger = _queue_priority_fixture(gate)
    grant = {
        "grant_id": "SCOPE-GRANT-PCS-BLOCKED",
        "authorization": {
            "approved_scope": "single_run_queue_priority",
            "blocked_tools": ["lab_scheduler.prioritize"],
        },
        "source": {"requested_scope": trigger["requested_scope"]},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    regate = gate.evaluate_with_grant(
        ai_output={"summary": "Prioritize after grant with blocked tool list."},
        requested_tool="lab_scheduler.prioritize",
        requested_action="prioritize_next_run",
        context=AKTAContext.from_dict({
            "evidence_state": "E5_internally_replicated_evidence",
            "validation_status": "V5_independently_replicated",
        }),
        deployment_profile="P5_review_gated_experimental_planner",
        domain_overlay="generic_lab_v0",
        scope_grant=grant,
        record=record,
        trigger=trigger,
    )
    regate_dict = regate.to_dict()
    out = export_pcs_bundle(
        AKTARecord(record),
        tmp_path / "pcs_blocked_grant",
        decision=regate_dict,
        scope_grant=grant,
        validate=True,
    )
    exported_grant = (out / "scope_grant.json").read_text(encoding="utf-8")
    exported_decision = (out / "akta_decision.json").read_text(encoding="utf-8")
    assert "SCOPE-GRANT-PCS-BLOCKED" in exported_grant
    assert regate_dict["admissibility"] in exported_decision
    assert "lab_scheduler.prioritize" in exported_decision
