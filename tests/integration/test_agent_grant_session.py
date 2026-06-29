"""Session grant store integration tests (v1.0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta import AKTAGate, AKTAContext
from akta.session_grant_store import SessionGrantStore
from adapters.langgraph.middleware import AKTALangGraphMiddleware

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def gate() -> AKTAGate:
    return AKTAGate.from_policy_dir(ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_session_grant_store_expiry_invalidation() -> None:
    store = SessionGrantStore()
    grant = {"expires_at": "2020-01-01T00:00:00Z", "authorization": {"approved_scope": "protocol_draft"}}
    store.put("sess-1", grant, bound_evidence_state="E4_internally_consistent_evidence")
    ctx, entry = store.apply_to_context("sess-1", {"evidence_state": "E4_internally_consistent_evidence"})
    assert entry is not None
    assert entry.invalidated is True


def test_middleware_multi_turn_grant_persistence(gate: AKTAGate) -> None:
    mw = AKTALangGraphMiddleware(
        policy_dir=str(ROOT / "policy"),
        overlays_dir=str(ROOT / "overlays"),
    )
    decision = gate.evaluate(
        ai_output={"summary": "Update active protocol."},
        requested_tool="protocol_editor.update_active_protocol",
        requested_action="update",
        context=AKTAContext.from_dict({"evidence_state": "E4_internally_consistent_evidence"}),
        deployment_profile="P4_protocol_drafting_assistant",
        domain_overlay="generic_lab_v0",
    )
    trigger = decision.to_dict().get("review_trigger")
    assert trigger
    grant = {
        "authorization": {"approved_scope": "protocol_draft"},
        "source": {"requested_scope": trigger["requested_scope"]},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    first = mw.retry_with_grant(grant, "protocol_editor.draft_change", "draft")
    second = mw.evaluate_tool("protocol_editor.draft_change", "draft")
    assert second.admissibility == first.admissibility
