"""Tests for LangGraph-style AKTA middleware."""

from __future__ import annotations

from pathlib import Path

import pytest

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
    with pytest.raises(PermissionError, match="AKTA blocked"):
        gated(
            ai_output={"summary": "Prioritize B."},
            context={"evidence_state": "E2_preliminary_signal"},
        )
