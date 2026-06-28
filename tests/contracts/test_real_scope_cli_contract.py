"""SCOPE real CLI mode contract tests (mock subprocess with real command shapes)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from adapters.scope.client import ADAPTER_MODE_CLI, submit_review_trigger

ROOT = Path(__file__).resolve().parent.parent.parent


def _make_cli_side_effect(tmp_path: Path):
    """Simulate scope packet create / decision submit / grant issue CLI chain."""
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        proc = type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        if cmd[1:3] == ["packet", "create"]:
            trigger = json.loads(Path(cmd[cmd.index("--trigger") + 1]).read_text(encoding="utf-8"))
            out = Path(cmd[cmd.index("--out") + 1])
            out.write_text(json.dumps({"packet_type": "scope_review_packet", "trigger": trigger}), encoding="utf-8")
        elif cmd[1:3] == ["decision", "submit"]:
            granted = cmd[cmd.index("--grant-scope") + 1]
            reviewer = cmd[cmd.index("--reviewer") + 1]
            out = Path(cmd[cmd.index("--out") + 1])
            out.write_text(json.dumps({"status": "granted", "granted_scope": granted, "reviewer_id": reviewer}), encoding="utf-8")
        elif cmd[1:3] == ["grant", "issue"]:
            decision = json.loads(Path(cmd[cmd.index("--decision") + 1]).read_text(encoding="utf-8"))
            out = Path(cmd[cmd.index("--out") + 1])
            out.write_text(json.dumps({
                "grant_id": "SCOPE-GRANT-CLI01",
                "granted_scope": decision["granted_scope"],
                "requested_scope": "active_protocol_update",
                "reviewer_id": decision.get("reviewer_id"),
                "review_trigger_id": "AKTA-REVTRIG-CLI01",
            }), encoding="utf-8")
        return proc

    return fake_run, calls


def test_scope_cli_real_command_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-CLI01",
        "requested_scope": "active_protocol_update",
        "required_review_role": "protocol_owner",
    }
    monkeypatch.setenv("SCOPE_CLI", "scope")
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)

    side_effect, calls = _make_cli_side_effect(Path("."))
    with patch("adapters.scope.client.subprocess.run", side_effect=side_effect):
        result = submit_review_trigger(trigger, grant_scope="protocol_draft", reviewer_id="protocol_owner")

    assert result.adapter_mode == ADAPTER_MODE_CLI
    assert result.error is None
    assert len(calls) == 3
    assert calls[0][:4] == ["scope", "packet", "create", "--trigger"]
    assert calls[1][:4] == ["scope", "decision", "submit", "--packet"]
    assert calls[2][:4] == ["scope", "grant", "issue", "--decision"]
    assert "--grant-scope" in calls[1]
    assert result.grant is not None
    assert result.grant["granted_scope"] == "protocol_draft"


def test_scope_cli_invalid_grant_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-CLI02",
        "requested_scope": "active_protocol_update",
    }
    monkeypatch.setenv("SCOPE_CLI", "scope")
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)

    side_effect, _ = _make_cli_side_effect(Path("."))
    with patch("adapters.scope.client.subprocess.run", side_effect=side_effect):
        result = submit_review_trigger(trigger, grant_scope="robot_queue_submission")

    assert result.adapter_mode == ADAPTER_MODE_CLI
    assert result.error is not None


def test_scope_cli_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    trigger = {
        "review_trigger_id": "AKTA-REVTRIG-CLI03",
        "requested_scope": "protocol_draft",
    }
    monkeypatch.setenv("SCOPE_CLI", "nonexistent-scope-cli-xyz")
    monkeypatch.delenv("SCOPE_REPO_PATH", raising=False)

    with patch("adapters.scope.client.subprocess.run", side_effect=FileNotFoundError("scope not found")):
        result = submit_review_trigger(trigger)

    assert result.adapter_mode == ADAPTER_MODE_CLI
    assert result.error is not None
