"""Tests for v0.4 adapters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from unittest.mock import patch

from akta.errors import AKTAReviewRequired
from adapters.guardrails.openai_adapter import OpenAIGuardrailAdapter
from adapters.langgraph.middleware import AKTALangGraphMiddleware
from adapters.pcs_bench.export_suite import export_from_jsonl
from adapters.scope.client import submit_review_trigger

ROOT = Path(__file__).resolve().parent.parent


def test_scope_adapter_simulated_mode() -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-TEST0001",
        "requested_scope": "active_protocol_update",
        "required_review_role": "protocol_owner",
        "blocked_tools": ["protocol_editor.update_active_protocol"],
    }
    result = submit_review_trigger(trigger, grant_scope="protocol_draft")
    assert result.adapter_mode == "simulated"
    assert result.grant is not None
    assert result.grant["granted_scope"] == "protocol_draft"


def test_langgraph_review_required_raises_typed_error() -> None:
    mw = AKTALangGraphMiddleware(
        policy_dir=str(ROOT / "policy"),
        overlays_dir=str(ROOT / "overlays"),
        deployment_profile="P5_review_gated_experimental_planner",
    )
    with pytest.raises(AKTAReviewRequired):
        mw.wrap_tool(lambda: None, "experiment_planner.create_run_plan", "create_plan")(
            ai_output={"summary": "Create run plan for replicated batch."},
            context={"evidence_state": "E5_internally_replicated_evidence"},
        )


def test_langgraph_draft_only_allows_non_mutating() -> None:
    mw = AKTALangGraphMiddleware(
        policy_dir=str(ROOT / "policy"),
        overlays_dir=str(ROOT / "overlays"),
        deployment_profile="P4_protocol_drafting_assistant",
    )
    called = {"ok": False}

    def draft_fn() -> str:
        called["ok"] = True
        return "draft"

    wrapped = mw.wrap_tool(draft_fn, "protocol_editor.draft_change", "draft")
    wrapped(
        ai_output={"summary": "Draft protocol tweak"},
        context={"evidence_state": "E4_internally_consistent_evidence"},
    )
    assert called["ok"] is True


def test_openai_guardrail_adapter_structure() -> None:
    adapter = OpenAIGuardrailAdapter(
        policy_dir=str(ROOT / "policy"),
        overlays_dir=str(ROOT / "overlays"),
        deployment_profile="P5_review_gated_experimental_planner",
    )
    with pytest.raises(AKTAReviewRequired):
        adapter.check_tool_call(
            "experiment_planner.create_run_plan",
            "create_plan",
            ai_output={"summary": "Create run plan"},
            context={"evidence_state": "E5_internally_replicated_evidence"},
        )


def test_pcs_bench_export(tmp_path: Path) -> None:
    out = export_from_jsonl(
        ROOT / "scenarios" / "canonical_5.jsonl",
        tmp_path / "suite.jsonl",
    )
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 5
    first = json.loads(lines[0])
    assert "inputs" in first
    assert first["suite_id"] == "akta-pcs-bench-v0.5"


def test_scope_adapter_cli_mode_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-SUBPROC01",
        "requested_scope": "active_protocol_update",
        "required_review_role": "protocol_owner",
    }
    scope_output = json.dumps({
        "packet_type": "scope_review_packet",
        "trigger": trigger,
    })

    class FakeProc:
        returncode = 0
        stdout = scope_output
        stderr = ""

    def fake_run(cmd, **kwargs):
        proc = FakeProc()
        if cmd[1:3] == ["packet", "create"]:
            out = Path(cmd[cmd.index("--out") + 1])
            out.write_text(scope_output, encoding="utf-8")
        elif cmd[1:3] == ["decision", "submit"]:
            granted = cmd[cmd.index("--grant-scope") + 1]
            out = Path(cmd[cmd.index("--out") + 1])
            out.write_text(json.dumps({"status": "granted", "granted_scope": granted}), encoding="utf-8")
        elif cmd[1:3] == ["grant", "issue"]:
            out = Path(cmd[cmd.index("--out") + 1])
            out.write_text(json.dumps({
                "grant_id": "SCOPE-GRANT-SUBPROC01",
                "granted_scope": "protocol_draft",
                "requested_scope": "active_protocol_update",
                "reviewer_id": "scope_reviewer",
                "review_trigger_id": "AKTA-REVTRIG-SUBPROC01",
            }), encoding="utf-8")
        return proc

    monkeypatch.setenv("SCOPE_CLI", "scope-mock")
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)

    with patch("adapters.scope.client.subprocess.run", side_effect=fake_run):
        result = submit_review_trigger(trigger, grant_scope="protocol_draft")

    assert result.adapter_mode == "cli"
    assert result.error is None
    assert result.grant is not None
    assert result.grant["granted_scope"] == "protocol_draft"


def test_scope_adapter_cli_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-MISSING01",
        "requested_scope": "protocol_draft",
    }
    monkeypatch.setenv("SCOPE_CLI", "nonexistent-scope-cli-xyz")

    with patch(
        "adapters.scope.client.subprocess.run",
        side_effect=FileNotFoundError("scope not found"),
    ):
        result = submit_review_trigger(trigger)

    assert result.adapter_mode == "cli"
    assert result.error is not None
