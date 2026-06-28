"""Tests for LangGraph-style AKTA middleware."""

from __future__ import annotations

from pathlib import Path

import pytest

from akta.errors import AKTAReviewRequired
from adapters.langgraph.middleware import AKTALangGraphMiddleware

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def middleware() -> AKTALangGraphMiddleware:
    return AKTALangGraphMiddleware(
        policy_dir=str(ROOT / "policy"),
        overlays_dir=str(ROOT / "overlays"),
        deployment_profile="P2_analysis_assistant",
        domain_overlay="generic_lab_v0",
    )


def test_wrap_tool_allows_literature_search(middleware: AKTALangGraphMiddleware) -> None:
    called: list[str] = []

    def tool_fn() -> str:
        called.append("executed")
        return "ok"

    gated = middleware.wrap_tool(tool_fn, "literature_search.query", "search")
    assert gated(context={"evidence_state": "E0_no_evidence"}) == "ok"
    assert called == ["executed"]


def test_wrap_tool_blocks_prioritization(middleware: AKTALangGraphMiddleware) -> None:
    def tool_fn() -> None:
        raise AssertionError("tool must not run when AKTA blocks")

    gated = middleware.wrap_tool(
        tool_fn,
        "lab_scheduler.prioritize",
        "prioritize_next_run",
    )
    with pytest.raises((PermissionError, AKTAReviewRequired)):
        gated(
            ai_output={"summary": "Prioritize B."},
            context={"evidence_state": "E2_preliminary_signal"},
        )


def test_retry_with_grant_uses_scope_metadata() -> None:
    mw = AKTALangGraphMiddleware(
        policy_dir=str(ROOT / "policy"),
        overlays_dir=str(ROOT / "overlays"),
        deployment_profile="P5_review_gated_experimental_planner",
        domain_overlay="generic_lab_v0",
    )
    grant = {
        "grant_id": "SCOPE-GRANT-LG-RETRY",
        "authorization": {
            "approved_scope": "single_run_queue_priority",
            "blocked_tools": ["lab_scheduler.prioritize"],
        },
        "source": {"requested_scope": "single_run_queue_priority"},
        "expires_at": "2030-01-01T00:00:00Z",
    }
    result = mw.retry_with_grant(
        grant,
        "lab_scheduler.prioritize",
        "prioritize_next_run",
        ai_output={"summary": "Retry after grant."},
        context={
            "evidence_state": "E5_internally_replicated_evidence",
            "validation_status": "V5_independently_replicated",
        },
    )
    assert result.admissibility == "blocked"
    assert "lab_scheduler.prioritize" in result.decision.get("blocked_tools", [])
