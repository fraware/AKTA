"""Tests for MCP stdio server (adapters/mcp/server.py)."""

from __future__ import annotations

import json
from pathlib import Path

from adapters.mcp.server import AKTAMCPServer

ROOT = Path(__file__).resolve().parent.parent


def _server() -> AKTAMCPServer:
    return AKTAMCPServer(policy_dir=ROOT / "policy", overlays_dir=ROOT / "overlays")


def test_mcp_initialize() -> None:
    resp = _server().handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp["id"] == 1
    assert "protocolVersion" in resp["result"]


def test_mcp_tools_list() -> None:
    resp = _server().handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert "akta_evaluate" in names
    assert "akta_evaluate_with_grant" in names
    assert "akta_export" in names


def test_mcp_evaluate_blocks_weak_evidence() -> None:
    resp = _server().handle({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "akta_evaluate",
            "arguments": {
                "ai_output": {"summary": "Prioritize condition B."},
                "requested_tool": "lab_scheduler.prioritize",
                "requested_action": "prioritize_next_run",
                "deployment_profile": "P2_analysis_assistant",
                "domain_overlay": "generic_lab_v0",
                "context": {"evidence_state": "E2_preliminary_signal"},
            },
        },
    })
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["admissibility"] == "blocked"
    assert payload["policy_hash"].startswith("sha256:")


def test_mcp_evaluate_with_grant_blocks_listed_tool() -> None:
    resp = _server().handle({
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "akta_evaluate_with_grant",
            "arguments": {
                "ai_output": {"summary": "Prioritize after grant."},
                "requested_tool": "lab_scheduler.prioritize",
                "requested_action": "prioritize_next_run",
                "deployment_profile": "P5_review_gated_experimental_planner",
                "domain_overlay": "generic_lab_v0",
                "context": {
                    "evidence_state": "E5_internally_replicated_evidence",
                    "validation_status": "V5_independently_replicated",
                },
                "scope_grant": {
                    "grant_id": "SCOPE-GRANT-MCP-BLOCKED",
                    "authorization": {
                        "approved_scope": "single_run_queue_priority",
                        "blocked_tools": ["lab_scheduler.prioritize"],
                    },
                    "source": {"requested_scope": "single_run_queue_priority"},
                    "expires_at": "2030-01-01T00:00:00Z",
                },
            },
        },
    })
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["admissibility"] == "blocked"
    assert "lab_scheduler.prioritize" in payload.get("blocked_tools", [])


def test_mcp_unknown_method_error() -> None:
    resp = _server().handle({"jsonrpc": "2.0", "id": 4, "method": "unknown/method", "params": {}})
    assert resp["error"]["code"] == -32601
