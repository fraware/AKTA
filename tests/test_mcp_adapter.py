"""Tests for MCP-style AKTA wrapper."""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.mcp.wrapper import AKTAMCPWrapper

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def wrapper() -> AKTAMCPWrapper:
    return AKTAMCPWrapper(
        policy_dir=str(ROOT / "policy"),
        overlays_dir=str(ROOT / "overlays"),
    )


def test_tool_spec_schema(wrapper: AKTAMCPWrapper) -> None:
    spec = wrapper.tool_spec()
    assert spec["name"] == "akta_evaluate"
    assert "requested_tool" in spec["inputSchema"]["required"]


def test_call_blocks_weak_evidence_prioritization(wrapper: AKTAMCPWrapper) -> None:
    result = wrapper.call(
        {
            "ai_output": {"summary": "Prioritize condition B."},
            "requested_tool": "lab_scheduler.prioritize",
            "requested_action": "prioritize_next_run",
            "deployment_profile": "P2_analysis_assistant",
            "domain_overlay": "generic_lab_v0",
            "context": {"evidence_state": "E2_preliminary_signal"},
        }
    )
    assert result["admissibility"] == "blocked"
    assert "lab_scheduler.prioritize" in result["blocked_tools"]
    assert len(result["next_admissible_steps"]) > 0
    assert result["policy_hash"].startswith("sha256:")


def test_call_unknown_mutating_tool_abstains(wrapper: AKTAMCPWrapper) -> None:
    result = wrapper.call(
        {
            "ai_output": "mutate",
            "requested_tool": "unregistered.custom_mutator",
            "requested_action": "mutate_state",
            "deployment_profile": "P5_review_gated_experimental_planner",
            "context": {"evidence_state": "E4_internally_consistent_evidence"},
        }
    )
    assert result["admissibility"] == "abstain_insufficient_context"
